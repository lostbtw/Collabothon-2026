"""Who paid, and what follows (ticket #25, spec #3 "Who paid" decision table).

Deterministic, no LLM. Writes the answer onto a Match (`paid_by`, `payer`, `consequences`); never creates
Ledger entries (role 4 books them from the decided Match, D-20) or Recommendations (role 5).

Two entry points:
- `match_for_unmatched_document(...)`: a Document with no bank line on any connected account becomes a
  `document_no_transaction` Match with its own score and reasons (the hero receipt -> fixture `mat_412`).
- `apply_who_paid(match, ...)`: fills `paid_by`, `payer`, `consequences` on a Match that matching (#24) built
  for a document and a bank line.

Spec gaps filled here (see the PR): the score of a `document_no_transaction` Match follows fixture `mat_412`
(sender_is_employee 0.50, no_bank_line_on_connected_accounts 0.30, card not a company/owner card 0.06);
"owed to owner" is `reimbursement_owed` + `reimbursement_to` with role `owner`; "possible private" is rule
PL-PRIV-01 plus its note (the Match has no separate field for it).
"""
from datetime import date, timedelta
from decimal import Decimal

from .normalise.money import money, round_cents, to_decimal

BASE_CURRENCY = "PLN"
SIMPLIFIED_INVOICE_LIMIT = Decimal("450.00")  # PL-VAT-02, receipts with the buyer's NIP, 2026 only
CARD_LAG_DAYS = (-1, 5)  # same window as card matching (#24)
ACCOUNTANT = "Confirm with your accountant."

PL_VAT_01 = "PL-VAT-01"  # no company tax id on the document: input VAT not deductible
PL_VAT_02 = "PL-VAT-02"  # receipt <= 450 PLN with company NIP = simplified invoice, VAT deductible
PL_VAT_03 = "PL-VAT-03"  # foreign B2B services: reverse charge, neutral
PL_REIMB_01 = "PL-REIMB-01"  # reimbursing a documented cost is not salary (hint)
PL_PRIV_01 = "PL-PRIV-01"  # looks private, paid by the company (hint)

PRIVATE_WORDS = ("perfum", "kosmetyk", "zabawk", "toy", "grocer", "spożywcz", "spozywcz", "alkohol", "wine",
                 "wino", "playstation", "netflix", "spotify", "biżuteri", "jewel", "fitness", "siłownia", "gym")


# ---------- inputs ----------

def _nip(tax_id) -> str:
    return (tax_id or "").upper().removeprefix("PL").replace("-", "").replace(" ", "")


def _person_ref(person: dict | None) -> dict | None:
    if not person:
        return None
    return {"person_id": person.get("person_id"), "name": person.get("name"), "email": person.get("email"),
            "role": person.get("role", "unknown")}


def _cards(accounts: list[dict], kind: str) -> set[str]:
    return {c for a in accounts if a.get("kind") == kind for c in (a.get("card_last4") or [])}


def find_person(people: list[dict], email: str | None) -> dict | None:
    if not email:
        return None
    email = email.strip().lower()
    return next((p for p in people if (p.get("email") or "").lower() == email), None)


def owner_of(people: list[dict]) -> dict | None:
    return next((p for p in people if p.get("role") == "owner"), None)


def buyer_is_company(document: dict, company: dict) -> bool:
    return bool(_nip(document["buyer"].get("tax_id"))) and _nip(document["buyer"].get("tax_id")) == _nip(company["tax_id"])


# ---------- the decision table ----------

def classify_payer(document: dict, transaction: dict | None, accounts: list[dict], people: list[dict],
                   sender_email: str | None = None) -> tuple[str, dict | None]:
    """(paid_by, payer PersonRef | None)."""
    if transaction is not None:
        account = next((a for a in accounts if a["id"] == transaction["account_id"]), None)
        if account and account.get("kind") == "owner_private":
            return "owner_private", _person_ref(owner_of(people))
        return "company_account", None

    card = (document.get("payment") or {}).get("card_last4")
    if card and card in _cards(accounts, "company_bank"):
        return "company_account", None  # card line not booked yet
    if card and card in _cards(accounts, "owner_private"):
        return "owner_private", _person_ref(owner_of(people))

    sender = find_person(people, sender_email or (document.get("submitted_by") or {}).get("email"))
    if sender and sender.get("role") == "employee":
        return "employee_private", _person_ref(sender)
    return "unknown", None


def _vat_in_base(document: dict) -> Decimal | None:
    totals = document["totals"]
    vat = totals.get("vat")
    if vat is None and document.get("vat_lines"):
        vat = {"amount": str(sum(to_decimal(v["vat"]) for v in document["vat_lines"])),
               "currency": totals["gross"]["currency"]}
    if vat is None:
        return None
    amount = to_decimal(vat["amount"])
    if vat["currency"] == BASE_CURRENCY:
        return amount
    fx = totals.get("fx")
    return round_cents(amount * to_decimal(fx["rate"])) if fx else None


def _gross_in_base(document: dict) -> dict:
    totals = document["totals"]
    return totals.get("gross_base") or totals["gross"]


def looks_private(document: dict) -> bool:
    suggestion = document.get("category_suggestion") or {}
    if suggestion.get("category") == "owner_private":
        return True
    text = " ".join(line.get("description") or "" for line in document.get("lines") or []).lower()
    return any(w in text for w in PRIVATE_WORDS)


def consequences(document: dict, paid_by: str, payer: dict | None, company: dict) -> dict:
    """`Match.consequences` for one Document, from the spec's decision table."""
    rule_ids: list[str] = []
    notes: list[str] = []
    kind = "Receipt" if document["doc_type"] in ("receipt", "simplified_invoice") else "Invoice"
    vat = _vat_in_base(document)
    gross_base = _gross_in_base(document)
    has_vat = vat is not None and vat != 0

    reverse_charge = "reverse_charge" in (document.get("flags") or []) or any(
        v.get("rate") == "oo" for v in document.get("vat_lines") or [])
    if reverse_charge:
        vat_deductible = True
        rule_ids.append(PL_VAT_03)
        notes.append("Import of services: reverse charge, self-assessed VAT is neutral.")
    elif buyer_is_company(document, company):
        vat_deductible = True
        simplified = (document["doc_type"] in ("receipt", "simplified_invoice")
                      and gross_base["currency"] == BASE_CURRENCY
                      and to_decimal(gross_base["amount"]) <= SIMPLIFIED_INVOICE_LIMIT)
        if simplified:
            rule_ids.append(PL_VAT_02)
            notes.append("Receipt up to 450 PLN with the company tax id counts as a simplified invoice, "
                         "so its VAT is deductible.")
    elif has_vat:
        vat_deductible = False
        rule_ids.append(PL_VAT_01)
        notes.append(f"{kind} has no company tax id, so the company cannot deduct the "
                     f"{format(vat, ',.2f')} {BASE_CURRENCY} VAT.")
        if paid_by == "company_account":
            notes.append("Ask for an invoice to the company next time.")
    else:
        vat_deductible = None  # no VAT shown on the document: nothing to deduct or lose

    reimbursement_owed = reimbursement_to = None
    if paid_by in ("employee_private", "owner_private") and payer is not None:
        reimbursement_owed = money(gross_base["amount"], gross_base["currency"])
        reimbursement_to = payer
        rule_ids.append(PL_REIMB_01)
        notes.append("Reimbursing the documented cost is not salary." if paid_by == "employee_private"
                     else "The company owes the owner this amount.")

    if paid_by == "company_account" and looks_private(document):
        rule_ids.append(PL_PRIV_01)
        notes.append(f"This looks like a private purchase paid by the company. {ACCOUNTANT}")
    elif PL_REIMB_01 in rule_ids:
        notes[-1] = f"{notes[-1]} {ACCOUNTANT}"

    return {
        "reimbursement_owed": reimbursement_owed,
        "reimbursement_to": reimbursement_to,
        "vat_deductible": vat_deductible,
        "vat_amount": money(vat, BASE_CURRENCY) if has_vat else None,
        "vat_lost": money(vat, BASE_CURRENCY) if has_vat and vat_deductible is False else None,
        "rule_ids": rule_ids,
        "note": " ".join(notes) or None,
    }


def has_tax_consequence(c: dict) -> bool:
    """Anything here waits for the owner, always (spec #3). Reverse charge alone is neutral."""
    return bool(c.get("vat_lost") or c.get("reimbursement_owed") or PL_PRIV_01 in (c.get("rule_ids") or []))


def document_flags(document: dict, c: dict) -> list[str]:
    """Document flags implied by the consequences, merged with the existing ones (order kept, no repeats)."""
    flags = list(document.get("flags") or [])
    extra = []
    if c["vat_lost"]:
        extra += ["buyer_not_company", "vat_not_deductible"]
    if PL_PRIV_01 in c["rule_ids"]:
        extra.append("possible_private")
    return flags + [f for f in extra if f not in flags]


# ---------- Match builders ----------

def _search_window(document: dict, as_of: str | None) -> tuple[date, date]:
    issued = date.fromisoformat(document["issue_date"])
    start, end = issued + timedelta(days=CARD_LAG_DAYS[0]), issued + timedelta(days=CARD_LAG_DAYS[1])
    if as_of:
        end = min(end, date.fromisoformat(as_of))
    return start, end


def outgoing_lines_for_amount(document: dict, transactions: list[dict], account_ids: set[str], start: date,
                              end: date) -> list[dict]:
    gross = _gross_in_base(document)
    want = -to_decimal(gross["amount"])
    return [t for t in transactions
            if t["account_id"] in account_ids
            and start <= date.fromisoformat(t["booking_date"]) <= end
            and t["amount_base"]["currency"] == gross["currency"]
            and to_decimal(t["amount_base"]["amount"]) == want]


def match_for_unmatched_document(document: dict, *, company: dict, people: list[dict], accounts: list[dict],
                                 transactions: list[dict], now: str, as_of: str | None = None,
                                 sender_email: str | None = None) -> dict:
    """A Document that matching found no bank line for -> `document_no_transaction` Match."""
    company_accounts = [a for a in accounts if a.get("company_id") == company["id"]]
    account_ids = {a["id"] for a in company_accounts}
    paid_by, payer = classify_payer(document, None, company_accounts, people, sender_email)

    reasons = []
    if paid_by == "employee_private":
        address = sender_email or (document.get("submitted_by") or {}).get("email")
        reasons.append({"rule": "sender_is_employee", "weight": 0.5,
                        "detail": f"Forwarded to invoices@ by {address} (employee)"})
    if document.get("issue_date"):
        start, end = _search_window(document, as_of)
        if not outgoing_lines_for_amount(document, transactions, account_ids, start, end):
            gross = _gross_in_base(document)
            reasons.append({"rule": "no_bank_line_on_connected_accounts", "weight": 0.3,
                            "detail": f"No outgoing {format(to_decimal(gross['amount']), ',.2f')} {gross['currency']} "
                                      f"between {start.isoformat()} and {end.isoformat()} on "
                                      f"{len(company_accounts)} connected accounts"})
    card = (document.get("payment") or {}).get("card_last4")
    if card:
        company_cards, owner_cards = _cards(company_accounts, "company_bank"), _cards(company_accounts, "owner_private")
        if card in company_cards:
            reasons.append({"rule": "card_last4", "weight": 0.12,
                            "detail": f"Card *{card} is a company card; its bank line is not booked yet"})
        elif card in owner_cards:
            reasons.append({"rule": "card_last4", "weight": 0.12, "detail": f"Card *{card} is the owner's card"})
        else:
            known = [f"a company card ({', '.join('*' + c for c in sorted(company_cards))})" if company_cards else None,
                     f"the owner's card ({', '.join('*' + c for c in sorted(owner_cards))})" if owner_cards else None]
            reasons.append({"rule": "card_last4", "weight": 0.06,
                            "detail": f"Card *{card} on the {document['doc_type']} is not "
                                      + " nor ".join(k for k in known if k)})

    return {
        "id": "mat_" + document["id"].removeprefix("doc_"),
        "match_type": "document_no_transaction",
        "document_id": document["id"],
        "transaction_id": None,
        "other_document_id": None,
        "score": round(min(1.0, sum(r["weight"] for r in reasons)), 2),
        "reasons": reasons,
        "paid_by": paid_by,
        "payer": payer,
        "consequences": consequences(document, paid_by, payer, company),
        "status": "suggested",  # never auto-confirmed without a bank line
        "decided_by": None,
        "decided_at": None,
        "created_at": now,
    }


def apply_who_paid(match: dict, document: dict, transaction: dict | None, *, company: dict, people: list[dict],
                   accounts: list[dict], sender_email: str | None = None) -> dict:
    """Fill `paid_by`, `payer` and `consequences` on a Match built by matching (#24). Returns a new dict."""
    paid_by, payer = classify_payer(document, transaction, accounts, people, sender_email)
    return {**match, "paid_by": paid_by, "payer": payer,
            "consequences": consequences(document, paid_by, payer, company)}
