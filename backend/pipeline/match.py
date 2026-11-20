"""Match scoring and assignment (ticket #24, spec #3 "Match score"). Deterministic, no LLM.

Scores every (Document, Transaction) pair with the spec's weights and hard filters, assigns greedily by
descending score one document to one bank line (threshold 0.55), fills who paid (#25) and routes the result:

| score | condition | status | control level |
|---|---|---|---|
| >= 0.90 | bank line in a known recurring series AND no tax consequence | auto_confirmed | analysed_autonomously |
| >= 0.90 | otherwise | suggested (one-click confirm) | approval_required |
| 0.55-0.90 | | suggested, with reasons and alternatives | approval_required |
| < 0.55 / no line | | document_no_transaction Match (#25) | recommendation |

Beyond the spec's table: when a cross-currency card line states its original amount (e.g. "45.00 USD"), it must
equal the invoice's gross for the full 0.35; within 1.00 (an OCR misread) it scores 0.25; further off is no match.
Without it, two invoices from the same foreign seller in the same week both fit the spread band and tie.

`recurring_series_id` is set by role 4's forecast engine; until it is, nothing auto-confirms (safe default).
Undo of an auto-confirmation = reject through the match decision endpoint (#42).
"""
import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from .normalise.money import to_decimal
from .who_paid import apply_who_paid, has_tax_consequence, match_for_unmatched_document

THRESHOLD = 0.55
AUTO = 0.90
FX_BAND = (Decimal("-0.005"), Decimal("0.045"))  # bank amount vs gross x NBP rate (card spread)
CARD_LAG = (-1, 5)
TRANSFER_GRACE_DAYS = 30
SYSTEM = {"role": "system", "person_id": None, "name": "rule: auto-confirm >= 0.90 for known recurring series",
          "email": None}

_LEGAL = {"sp", "z", "o", "sa", "s", "a", "inc", "ltd", "llc", "gmbh", "pty", "ag", "co", "com", "sample",
          "spolka", "spółka", "akcyjna", "the"}


# ---------- signals ----------

def _norm(text) -> str:
    text = (text or "").lower().replace("(sample)", " ").replace("sp. z o.o.", " ").replace("s.a.", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", text)).strip()


def name_similarity(seller: str, bank_text: str) -> float:
    """Spike 04's measure (token overlap or sequence ratio), plus "the seller's core name appears in the bank
    text" for card descriptors like 'PIXELBOARD.COM* SAN FRANCISCO'."""
    a, b = _norm(seller), _norm(bank_text)
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    ratio = SequenceMatcher(None, a, b).ratio()
    core = [t for t in a.split() if t not in _LEGAL and len(t) >= 3]
    contained = 0.9 if core and all(any(w.startswith(t) for w in tb) for t in core) else 0.0
    core_b = [t for t in b.split() if t not in _LEGAL]
    core_ratio = SequenceMatcher(None, " ".join(core), " ".join(core_b)).ratio() if core and core_b else 0.0
    return round(max(overlap, ratio, contained, core_ratio), 2)


def _alnum(text) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def _iban_core(text) -> str:
    s = _alnum(text)
    return s[2:] if len(s) > 2 and s[:2].isalpha() else s


def _fmt(x: Decimal) -> str:
    return format(x, ",.2f")


def score_pair(doc: dict, txn: dict, accounts: dict) -> tuple[float, list[dict]]:
    """(score, reasons). Score 0 and no reasons when a hard filter fails."""
    amount = to_decimal(txn["amount_base"]["amount"])
    if (doc["direction"] == "purchase") != (amount < 0):
        return 0.0, []
    paid = abs(amount)
    txn_ccy = txn["amount_base"]["currency"]
    gross = doc["totals"]["gross"]
    reasons = []

    # amount (hard filter)
    if gross["currency"] == txn_ccy:
        want = to_decimal(gross["amount"])
        if paid == want:
            reasons.append({"rule": "amount_exact", "weight": 0.5, "detail": f"{_fmt(paid)} {txn_ccy} equal"})
        elif abs(paid - want) <= 1:
            reasons.append({"rule": "amount_near", "weight": 0.3,
                            "detail": f"{_fmt(paid)} vs {_fmt(want)} {txn_ccy} (within 1.00)"})
        else:
            return 0.0, []
    else:
        base = doc["totals"].get("gross_base")
        fx = doc["totals"].get("fx")
        if not base or base["currency"] != txn_ccy or not fx:
            return 0.0, []
        expected = to_decimal(base["amount"])
        if expected == 0:
            return 0.0, []
        diff = (paid - expected) / expected
        if not FX_BAND[0] <= diff <= FX_BAND[1]:
            return 0.0, []
        # The card line states the foreign amount it charged: a different amount is a different purchase,
        # a slightly different one (OCR misread on the document) is possible but ranks lower.
        weight, note = 0.35, ""
        original = txn.get("original_amount")
        if original and original["currency"] == gross["currency"]:
            gap = abs(abs(to_decimal(original["amount"])) - to_decimal(gross["amount"]))
            if gap > 1:
                return 0.0, []
            if gap > 0:
                weight, note = 0.25, f"; the line states {_fmt(abs(to_decimal(original['amount'])))} {gross['currency']}"
        reasons.append({"rule": "amount_fx_within_spread", "weight": weight,
                        "detail": f"{_fmt(to_decimal(gross['amount']))} {gross['currency']} x NBP {fx['rate']} = "
                                  f"{_fmt(expected)} {txn_ccy}; bank charged {_fmt(paid)} {txn_ccy} "
                                  f"({diff * 100:+.1f}%, inside the -0.5..+4.5% card spread band){note}"})

    # date (hard filter)
    if not doc.get("issue_date"):
        return 0.0, []
    issued = date.fromisoformat(doc["issue_date"])
    booked = date.fromisoformat(txn["booking_date"])
    lag = (booked - issued).days
    if txn.get("transaction_type") == "card_payment" or txn.get("card_last4"):
        if not CARD_LAG[0] <= lag <= CARD_LAG[1]:
            return 0.0, []
        days = abs(lag)
    else:
        due = date.fromisoformat(doc["due_date"]) if doc.get("due_date") else issued
        if not -1 <= lag <= (due - issued).days + TRANSFER_GRACE_DAYS:
            return 0.0, []
        days = abs((booked - due).days)
    weight = round(max(0.0, 0.2 - 0.02 * days), 2)
    reasons.append({"rule": "date_lag", "weight": weight,
                    "detail": "Booked on the invoice date" if lag == 0 else
                    f"Booked {abs(lag)} day{'s' if abs(lag) != 1 else ''} {'after' if lag > 0 else 'before'} invoice date"})

    # soft signals
    number = _alnum(doc.get("number"))
    if len(number) >= 4 and number in _alnum(txn.get("description")):
        reasons.append({"rule": "invoice_number_in_title", "weight": 0.4,
                        "detail": f"Invoice number {doc['number']} in the transfer title"})
    bank_name = " ".join(x for x in (txn.get("counterparty_name_raw"), txn.get("description")) if x)
    sim = name_similarity(doc["seller"]["name"], bank_name)
    if sim > 0:
        reasons.append({"rule": "name_similarity", "weight": round(0.3 * sim, 2),
                        "detail": f"'{doc['seller']['name']}' ~ '{txn.get('counterparty_name_raw') or txn.get('description')}' ({sim:.2f})"})
    card = (doc.get("payment") or {}).get("card_last4")
    if card and card == txn.get("card_last4"):
        kind = (accounts.get(txn["account_id"]) or {}).get("kind")
        whose = "Owner's card" if kind == "owner_private" else "Company card"
        reasons.append({"rule": "card_last4", "weight": 0.12, "detail": f"{whose} *{card}"})
    iban = _iban_core((doc.get("payment") or {}).get("bank_account"))
    if iban and iban == _iban_core(txn.get("counterparty_account")):
        reasons.append({"rule": "iban_equal", "weight": 0.3, "detail": "Bank account on the invoice equals the payee's"})

    return round(min(1.0, sum(r["weight"] for r in reasons)), 2), reasons


# ---------- assignment and routing ----------

def run_matching(documents: list[dict], transactions: list[dict], *, company: dict, people: list[dict],
                 accounts: list[dict], now: str, as_of: str | None = None,
                 senders: dict | None = None) -> list[dict]:
    """One result per golden Document: {"match", "control_level", "alternatives"}.

    `senders` maps document id -> forwarding address (RawItem metadata), used by who paid for unmatched documents.
    Transactions already matched (match_status != unmatched) are not offered again.
    """
    senders = senders or {}
    company_accounts = [a for a in accounts if a.get("company_id") == company["id"]]
    by_account = {a["id"]: a for a in company_accounts}
    docs = [d for d in documents if d.get("status") != "duplicate" and d["company_id"] == company["id"]]
    lines = [t for t in transactions if t["account_id"] in by_account
             and t.get("match_status", "unmatched") in ("unmatched", "missing_document")]  # a late receipt still fits

    candidates = []  # (score, doc index, txn index, reasons)
    for di, doc in enumerate(docs):
        for ti, txn in enumerate(lines):
            s, reasons = score_pair(doc, txn, by_account)
            if s >= THRESHOLD:
                candidates.append((s, di, ti, reasons))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    taken_doc, taken_txn, chosen = set(), set(), {}
    for s, di, ti, reasons in candidates:
        if di in taken_doc or ti in taken_txn:
            continue
        taken_doc.add(di)
        taken_txn.add(ti)
        chosen[di] = (s, ti, reasons)

    results = []
    for di, doc in enumerate(docs):
        if di not in chosen:
            match = match_for_unmatched_document(doc, company=company, people=people, accounts=accounts,
                                                 transactions=transactions, now=now, as_of=as_of,
                                                 sender_email=senders.get(doc["id"]))
            results.append({"match": match, "control_level": "recommendation", "alternatives": []})
            continue
        s, ti, reasons = chosen[di]
        txn = lines[ti]
        match = apply_who_paid({
            "id": "mat_" + doc["id"].removeprefix("doc_"),
            "match_type": "document_transaction" if doc["direction"] == "purchase" else "sales_invoice_payment",
            "document_id": doc["id"], "transaction_id": txn["id"], "other_document_id": None,
            "score": s, "reasons": reasons, "status": "suggested",
            "decided_by": None, "decided_at": None, "created_at": now,
        }, doc, txn, company=company, people=people, accounts=company_accounts, sender_email=senders.get(doc["id"]))
        auto = s >= AUTO and txn.get("recurring_series_id") and not has_tax_consequence(match["consequences"])
        if auto:
            match.update(status="auto_confirmed", decided_by=SYSTEM, decided_at=now)
        alternatives = [{"transaction_id": lines[t]["id"], "score": sc}
                        for sc, d, t, _ in candidates if d == di and t != ti][:3]
        results.append({"match": match, "control_level": "analysed_autonomously" if auto else "approval_required",
                        "alternatives": alternatives})
    return results


def match_suggested_payload(match: dict) -> dict:
    """Small payload for the `match.suggested` event (contracts/events.md)."""
    return {"match_id": match["id"], "document_id": match["document_id"], "transaction_id": match["transaction_id"],
            "paid_by": match["paid_by"], "score": match["score"]}
