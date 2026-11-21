"""Seam: Match + Document -> Ledger entries. Pure, no database."""
from datetime import date

from backend.db.contracts import LedgerEntry
from backend.db.fixtures import read
from backend.finance.ledger import entries_for_match, next_pay_run


def fixture(entity, id):
    return next(x for x in read(entity) if x["id"] == id)


def confirmed(match, **changes):
    return {**match, "status": "confirmed", **changes}


MAT_412 = fixture("match", "mat_412")
DOC_412 = fixture("document", "doc_rcpt412")


def test_approving_jans_receipt_books_the_expense_and_the_debt_to_jan_with_the_vat_lost():
    expense, debt = entries_for_match(confirmed(MAT_412), DOC_412, "apr_1")

    assert expense["type"] == "expense"
    assert expense["amount"] == {"amount": "-1299.00", "currency": "PLN"}
    assert expense["vat"]["amount"] == {"amount": "242.90", "currency": "PLN"}
    assert expense["vat"]["deductible"] is False
    assert expense["paid_by"] == "employee_private"
    assert expense["category"] == "equipment"
    assert debt["type"] == "reimbursement_liability"
    assert debt["amount"] == {"amount": "-1299.00", "currency": "PLN"}
    assert "Jan Kowalski" in debt["explanation"]
    assert debt["cash_date"] == "2026-11-30"
    for entry in (expense, debt):
        assert entry["status"] == "approved" and entry["approval_id"] == "apr_1"
        assert entry["match_id"] == "mat_412" and entry["evidence"]
        LedgerEntry.model_validate(entry)


def test_a_rejected_match_books_nothing():
    assert entries_for_match({**MAT_412, "status": "rejected"}, DOC_412, "apr_1") == []


def test_an_auto_confirmed_subscription_is_booked_without_an_approval():
    """PixelBoard: auto-confirmed by rule (known recurring series), no owner approval to point to."""
    match, document = fixture("match", "mat_pixel11"), fixture("document", "doc_pixel11")
    (expense,) = entries_for_match(match, document, None,
                                   transaction={"id": "txn_731", "booking_date": "2026-11-20"})

    assert (expense["status"], expense["approval_id"], expense["paid_by"]) == ("approved", None, "company_account")
    assert expense["amount_base"]["currency"] == "PLN"
    assert expense["cash_date"] == "2026-11-20"
    LedgerEntry.model_validate(expense)


def test_a_purchase_paid_from_the_company_account_books_only_the_expense():
    match = confirmed(MAT_412, paid_by="company_account", payer=None, transaction_id="txn_9",
                      consequences={"vat_deductible": True, "vat_amount": {"amount": "242.90", "currency": "PLN"},
                                    "reimbursement_owed": None, "reimbursement_to": None, "vat_lost": None})
    (expense,) = entries_for_match(match, DOC_412, "apr_2", transaction={"id": "txn_9", "booking_date": "2026-11-21"})

    assert expense["vat"]["deductible"] is True
    assert expense["cash_date"] == "2026-11-21"
    assert expense["transaction_id"] == "txn_9"
    LedgerEntry.model_validate(expense)


def test_a_purchase_on_the_owners_card_books_a_debt_to_the_owner():
    owner = {"person_id": "per_tomek", "name": "Tomasz Borsuk (SAMPLE)", "role": "owner"}
    match = confirmed(MAT_412, paid_by="owner_private", payer=owner,
                      consequences={**MAT_412["consequences"], "reimbursement_to": owner})
    counterparties = [{"id": "cp_tomek", "person_id": "per_tomek"}]

    expense, debt = entries_for_match(match, DOC_412, "apr_3", counterparties=counterparties)

    assert expense["paid_by"] == "owner_private"
    assert debt["counterparty_id"] == "cp_tomek"
    assert "the owner, Tomasz Borsuk" in debt["explanation"]


def test_sales_duplicates_and_payouts_book_nothing_here():
    sale = {**DOC_412, "direction": "sale"}
    assert entries_for_match(confirmed(MAT_412), sale, "apr_4") == []
    for match_type in ("duplicate_document", "sales_invoice_payment", "reimbursement_payout"):
        assert entries_for_match(confirmed(MAT_412, match_type=match_type), DOC_412, "apr_4") == []


def test_the_same_match_always_gives_the_same_entry_ids():
    first = [e["id"] for e in entries_for_match(confirmed(MAT_412), DOC_412, "apr_1")]
    again = [e["id"] for e in entries_for_match(confirmed(MAT_412), DOC_412, "apr_1")]
    assert first == again == ["led_mat_412_exp", "led_mat_412_reimb"]


def test_the_pay_run_is_the_last_business_day_of_the_month():
    assert next_pay_run(date(2026, 11, 20)) == date(2026, 11, 30)
    assert next_pay_run(date(2026, 5, 10)) == date(2026, 5, 29)  # 31 May is a Sunday
