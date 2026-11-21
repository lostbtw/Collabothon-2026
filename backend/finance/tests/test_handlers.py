"""Seam: outbox -> finance consumer -> Ledger (#27). Needs the test database (backend/conftest.py)."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.db.events import events_after, new_event, publish
from backend.db.fixtures import load_fixtures
from backend.db.store import Store
from backend.finance import engine
from backend.finance.main import process_pending


@pytest.fixture
def demo(db, db_url):
    """The API on the fixture data (role 5's stand-ins), as in backend/api/tests."""
    load_fixtures(db)
    with TestClient(create_app(database_url=db_url)) as c:
        yield c


def events(db, type):
    return [e for _, e in events_after(db, 0, limit=1000) if e["type"] == type]


def booked(db, match_id="mat_412"):
    return {e["type"]: e for e in Store(db).list("ledger_entry", match_id=match_id) if e["status"] == "approved"}


def test_approving_jans_receipt_books_two_approved_entries_and_the_summary_shows_them(demo, db):
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})
    process_pending(db)

    entries = booked(db)
    assert set(entries) == {"expense", "reimbursement_liability"}
    assert entries["expense"]["vat"] == {"amount": {"amount": "242.90", "currency": "PLN"}, "deductible": False,
                                         "reason": entries["expense"]["vat"]["reason"]}
    approval = entries["expense"]["approval_id"]
    assert approval and entries["reimbursement_liability"]["approval_id"] == approval
    assert {e["payload"]["ledger_entry_id"] for e in events(db, "ledger.entry.approved")} == \
        {e["id"] for e in entries.values()}
    kpis = demo.get("/api/v1/ledger/summary").json()["kpis"]
    assert kpis["vat_lost_ytd"]["amount"] == "242.90"
    assert kpis["reimbursements_owed"]["amount"] == "1299.00"


def test_the_same_decision_twice_books_once(demo, db):
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})
    process_pending(db)
    (decided,) = events(db, "match.decided")
    publish(db, new_event("match.decided", decided["company_id"], decided["payload"], producer="api"))
    process_pending(db)

    assert len(booked(db)) == 2
    assert len(Store(db).list("ledger_entry", match_id="mat_412")) == 2
    assert len(events(db, "ledger.entry.approved")) == 2


def test_a_rejected_match_books_nothing(demo, db):
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "rejected"})
    process_pending(db)

    assert booked(db) == {}
    assert events(db, "ledger.entry.approved") == []


def test_without_fixture_entries_the_booking_creates_its_own(db):
    load_fixtures(db)
    s = Store(db)
    db.execute("delete from ledger_entries")
    db.commit()
    s.put("match", {**s.get("match", "mat_412"), "status": "confirmed"})
    publish(db, new_event("match.decided", "co_borsuk",
                          {"match_id": "mat_412", "status": "confirmed", "approval_id": "apr_t"}, producer="api"))
    process_pending(db)

    assert {e["id"] for e in booked(db).values()} == {"led_mat_412_exp", "led_mat_412_reimb"}


def test_approving_the_hero_receipt_raises_vat_lost_this_year_by_242_90(demo, db):
    """#46: the counter counts approved entries only, so the owner's approval makes it tick up."""
    before = engine.ledger_kpis(db, "co_borsuk")
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})
    process_pending(db)
    after = engine.ledger_kpis(db, "co_borsuk")

    assert Decimal(after["vat_lost_ytd"]["amount"]) - Decimal(before["vat_lost_ytd"]["amount"]) == Decimal("242.90")
    assert after["vat_lost_ytd"] == {"amount": "242.90", "currency": "PLN"}
    assert Decimal(after["reimbursements_owed"]["amount"]) - Decimal(before["reimbursements_owed"]["amount"]) \
        == Decimal("1299.00")


def test_a_rejected_hero_receipt_leaves_vat_lost_this_year_unchanged(demo, db):
    before = engine.ledger_kpis(db, "co_borsuk")["vat_lost_ytd"]
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "rejected"})
    process_pending(db)

    assert engine.ledger_kpis(db, "co_borsuk")["vat_lost_ytd"] == before == {"amount": "0.00", "currency": "PLN"}


def test_the_summary_the_app_shows_rises_by_242_90_when_the_hero_receipt_is_approved(demo, db):
    """The Overview page asks for one month; 'VAT lost this year' must still be the whole year."""
    month = {"company_id": "co_borsuk", "group_by": "category", "from": "2026-11-01", "to": "2026-11-30"}
    before = demo.get("/api/v1/ledger/summary", params=month).json()["kpis"]
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})
    process_pending(db)
    after = demo.get("/api/v1/ledger/summary", params=month).json()["kpis"]

    assert before["vat_lost_ytd"] == {"amount": "0.00", "currency": "PLN"}
    assert after["vat_lost_ytd"] == {"amount": "242.90", "currency": "PLN"}
    assert after == engine.ledger_kpis(db, "co_borsuk")
