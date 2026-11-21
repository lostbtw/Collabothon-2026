"""Open invoices in the forecast: what a bank line clearly paid, or what is long overdue, is not money due tomorrow."""
from backend.db.fixtures import load_fixtures
from backend.db.store import Store
from backend.finance import engine


def invoice(id_, seller, amount, issued, due, direction="purchase"):
    party = {"name": seller, "tax_id": None}
    us = {"name": "Demo Company (SAMPLE)", "tax_id": "9990000014", "is_company": True}
    return {"id": id_, "company_id": "co_borsuk", "raw_item_ids": [f"raw_{id_}"], "doc_type": "invoice", "direction": direction,
            "channel": "email", "number": id_, "issue_date": issued, "due_date": due,
            "seller": party if direction == "purchase" else {k: v for k, v in us.items() if k != "is_company"},
            "buyer": us if direction == "purchase" else {**party, "is_company": False},
            "totals": {"gross": {"amount": amount, "currency": "PLN"}, "gross_base": {"amount": amount, "currency": "PLN"}},
            "extraction": {"method": "xml_parse", "confidence": 1.0}, "status": "approved", "flags": []}


def line(id_, date, amount, raw):
    return {"id": id_, "account_id": "acc_pln", "raw_item_id": f"raw_{id_}", "external_id": id_, "booking_date": date,
            "amount": {"amount": amount, "currency": "PLN"}, "amount_base": {"amount": amount, "currency": "PLN"},
            "counterparty_name_raw": raw, "description": raw, "status": "booked", "match_status": "unmatched"}


def test_paid_and_long_overdue_invoices_are_not_forecast(db):
    load_fixtures(db)
    s = Store(db)
    s.put("document", invoice("doc_paid", "Jan Nowak IT (SAMPLE)", "5000.00", "2026-10-01", "2026-10-15"), company_id="co_borsuk")
    s.put("transaction", line("txn_paid", "2026-10-14", "-5000.00", "JAN NOWAK (SAMPLE)"), company_id="co_borsuk")
    s.put("document", invoice("doc_stale", "Old Supplier (SAMPLE)", "7000.00", "2026-05-01", "2026-05-15"), company_id="co_borsuk")
    s.put("document", invoice("doc_open", "Fresh Supplier (SAMPLE)", "900.00", "2026-11-10", "2026-11-24"), company_id="co_borsuk")

    company = {"id": "co_borsuk", "name": "Demo Company (SAMPLE)"}
    ids = {i["id"] for i in engine._open_items(s, company, "2026-11-21")[0]}

    assert "doc_open" in ids
    assert "doc_paid" not in ids   # a payment of the same amount to the same name after the invoice
    assert "doc_stale" not in ids  # more than STALE_DAYS overdue with no payment found
