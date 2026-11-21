"""Ledger entries from a decided Match, booked as approved: the expense and, when someone paid privately, the debt to them."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

CREATED_BY = "rule:ledger_from_match_v1"
BOOKABLE_MATCH_TYPES = {"document_transaction", "document_no_transaction"}
CATEGORIES = {
    "revenue_services", "salaries", "contractors", "social_security", "taxes", "rent_office",
    "software_subscriptions", "cloud_hosting", "equipment", "travel", "marketing_ads", "professional_services",
    "bank_fees", "meals_representation", "reimbursements", "owner_private", "financing", "investment_outflow", "other",
}


def money(amount: Decimal | str, currency: str) -> dict[str, str]:
    """Money as in the contracts: decimal string with 2 places plus currency."""
    return {"amount": f"{Decimal(amount):.2f}", "currency": currency}


def negative(m: dict[str, str]) -> dict[str, str]:
    return money(-abs(Decimal(m["amount"])), m["currency"])


def shown(m: dict[str, str]) -> str:
    """'1,299.00 PLN' for explanations."""
    return f"{abs(Decimal(m['amount'])):,.2f} {m['currency']}"


def next_pay_run(day: date) -> date:
    """Last business day (Mon-Fri) of the month of `day`: when salaries and reimbursements are paid."""
    first_next = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = first_next - timedelta(days=1)
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last


DECIDED = ("confirmed", "auto_confirmed")  # by the owner, or by rule for a known recurring series (no approval)


def should_book(match: dict[str, Any], document: dict[str, Any] | None) -> bool:
    return (match.get("status") in DECIDED and match.get("match_type") in BOOKABLE_MATCH_TYPES
            and document is not None and document.get("direction") == "purchase")


def entries_for_match(match: dict[str, Any], document: dict[str, Any] | None, approval_id: str | None, *,
                      transaction: dict[str, Any] | None = None,
                      counterparties: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """The approved Ledger entries a confirmed purchase Match calls for; [] when it calls for none."""
    if not should_book(match, document):
        return []
    company = document.get("company_id") or match.get("company_id")
    c = match.get("consequences") or {}
    totals = document["totals"]
    gross = totals["gross"]
    gross_base = totals.get("gross_base") or gross
    doc_day = date.fromisoformat(document.get("sale_date") or document.get("issue_date") or match["created_at"][:10])
    paid_by = match.get("paid_by") or "unknown"
    payer = match.get("payer") or {}
    seller = document.get("seller") or {}
    what = ((document.get("lines") or [{}])[0].get("description") or "Purchase").removesuffix(" (SAMPLE)")
    pay_run = next_pay_run(doc_day)
    if transaction is not None:
        cash_day = transaction.get("booking_date")
    elif paid_by in ("employee_private", "owner_private"):
        cash_day = pay_run.isoformat()
    else:
        cash_day = None

    common = {
        "company_id": company, "date": doc_day.isoformat(), "fx": totals.get("fx"),
        "document_id": document["id"], "transaction_id": match.get("transaction_id"), "match_id": match["id"],
        "status": "approved", "approval_id": approval_id, "created_by": CREATED_BY,
    }
    document_link = {"kind": "document", "id": document["id"], "url": f"/documents/{document['id']}",
                     "label": f"{document.get('doc_type', 'document').replace('_', ' ').capitalize()}, "
                              f"{seller.get('name') or 'seller unknown'}, {shown(gross)}"}
    match_link = {"kind": "match", "id": match["id"], "url": f"/matches/{match['id']}",
                  "label": f"Who paid: {paid_by.replace('_', ' ')}"
                           + (f" ({payer['name']})" if payer.get("name") else "")}

    vat = None
    if c.get("vat_amount"):
        deductible = c.get("vat_deductible")
        vat = {"amount": c["vat_amount"], "deductible": bool(deductible),
               "reason": None if deductible else "No company tax id on the document, so the VAT cannot be deducted"}
    who = {"employee_private": f"bought by {payer.get('name', 'an employee')} with a private card",
           "owner_private": "paid with the owner's private card",
           "company_account": "paid from the company account"}.get(paid_by, "payer unknown")
    explanation = f"{what} from {seller.get('name') or 'an unknown seller'}, {shown(gross)}, {who}."
    if vat and not vat["deductible"]:
        explanation += f" VAT {shown(vat['amount'])} is lost: booked gross because it cannot be deducted."
    suggestion = (document.get("category_suggestion") or {}).get("category")
    entries = [{
        "id": f"led_{match['id']}_exp", **common, "cash_date": cash_day, "type": "expense",
        "category": suggestion if suggestion in CATEGORIES else "other", "cost_behaviour": None,
        "amount": negative(gross), "amount_base": negative(gross_base), "vat": vat,
        "counterparty_id": seller.get("counterparty_id"), "paid_by": paid_by,
        "explanation": explanation, "evidence": [document_link, match_link],
    }]

    owed = c.get("reimbursement_owed")
    if owed and Decimal(owed["amount"]) != 0:
        person = c.get("reimbursement_to") or payer
        name = person.get("name") or "the payer"
        to_owner = person.get("role") == "owner" or paid_by == "owner_private"
        counterparty = next((cp["id"] for cp in counterparties
                             if person.get("person_id") and cp.get("person_id") == person["person_id"]), None)
        entries.append({
            "id": f"led_{match['id']}_reimb", **common, "fx": None, "cash_date": pay_run.isoformat(),
            "type": "reimbursement_liability", "category": "reimbursements", "cost_behaviour": None,
            "amount": negative(owed), "amount_base": negative(owed), "vat": None,
            "counterparty_id": counterparty, "paid_by": "not_applicable",
            "explanation": (f"The company owes {'the owner, ' if to_owner else ''}{name} {shown(owed)} for "
                            f"{what.lower()} paid privately; planned payout with the pay run on {pay_run.isoformat()}."),
            "evidence": [match_link, document_link],
        })
    return entries
