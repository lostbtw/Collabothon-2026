"""Missing documents and documents without a payment (ticket #43, spec #3). Deterministic, no LLM.

Bank lines (Transaction.match_status, counted by role 5's ledger summary as `documents_missing`):
- money out with no document `GRACE_DAYS` after booking (counted from the company's as-of date) -> missing_document;
  only for lines from the last `LOOKBACK_DAYS`, so a year of history does not flood the owner;
- salaries, taxes, social security, bank fees, financing, investment transfers, internal transfers and card-payout
  income need no document -> no_document_needed.
Documents (purchase, no bank line, not forwarded by an employee or the owner):
- not yet due -> a known payable for the forecast, no question;
- due (or, without a due date, older than GRACE_DAYS) -> the `document_no_transaction` Match with paid_by unknown,
  which role 5 turns into the "Which payment is this?" question, with the document as evidence.
"""
from datetime import date, timedelta

from .counterparty import categorise

GRACE_DAYS = 5
LOOKBACK_DAYS = 35
NO_DOCUMENT_TYPES = {"salary", "tax", "social_security", "fee", "internal", "fx"}
NO_DOCUMENT_CATEGORIES = {"salaries", "social_security", "taxes", "bank_fees", "financing", "investment_outflow",
                          "reimbursements", "owner_private"}


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def line_status(txn: dict, as_of: str | None, lookback_days: int = LOOKBACK_DAYS) -> str | None:
    """New match_status for an unmatched bank line, or None to leave it as it is."""
    if txn.get("match_status", "unmatched") != "unmatched":
        return None
    outgoing = txn["amount_base"]["amount"].startswith("-")
    text = f"{txn.get('counterparty_name_raw') or ''} {txn.get('description') or ''}"
    category = txn.get("category") or categorise(text, counterparty=None, incoming=not outgoing)[0]
    if not outgoing:
        # card payouts and transfers between own accounts need no document; other money in waits for a sales invoice
        return "no_document_needed" if txn.get("transaction_type") in ("card_settlement", "internal") else None
    if txn.get("transaction_type") in NO_DOCUMENT_TYPES or category in NO_DOCUMENT_CATEGORIES:
        return "no_document_needed"
    today = _day(as_of) or date.today()
    booked = _day(txn["booking_date"])
    if today - timedelta(days=lookback_days) <= booked <= today - timedelta(days=GRACE_DAYS):
        return "missing_document"
    return None


def not_yet_due(doc: dict, as_of: str | None) -> bool:
    """An unpaid purchase that is still a payable, not a question. A paid one (a card receipt) is never a payable."""
    if (doc.get("payment") or {}).get("paid"):
        return False
    today = _day(as_of) or date.today()
    due = _day(doc.get("due_date"))
    if due:
        return due > today
    issued = _day(doc.get("issue_date"))
    return issued is not None and issued > today - timedelta(days=GRACE_DAYS)


def is_unpaid_question(match: dict) -> bool:
    """The Match shape that role 5 shows as "Which payment is this?" (score below 0.55)."""
    return match["match_type"] == "document_no_transaction" and match["paid_by"] == "unknown"


def documents_to_ask_about(documents: list[dict], matched_ids: set[str], as_of: str | None) -> list[dict]:
    """Golden purchase documents with no Match yet that are now due: the sweep matches them (and so asks)."""
    return [d for d in documents
            if d.get("status") not in ("duplicate", "rejected") and d.get("direction") == "purchase"
            and d["id"] not in matched_ids and not not_yet_due(d, as_of)]
