"""Seam: the ledger and forecast endpoints on the engine's data. Needs the test database."""
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.api import contract
from backend.api.app import create_app
from backend.db.fixtures import read
from backend.db.seed import seed
from backend.db.store import Store
from backend.finance import engine

from .data import CLOSED_JUNE, PIZZERIA_CSV, bank_lines
from .test_engine import labs_db  # noqa: F401  (fixture: Borsuk Labs in the database)

WAITS_FOR_ROLE_5 = pytest.mark.xfail(
    reason="role 5 wires GET /forecast/latest to engine.latest(); until then a fresh database has no forecast (404)")
PATHS = [
    ("get", "/ledger", "/ledger", {}),
    ("get", "/ledger/summary", "/ledger/summary", {}),
    pytest.param("get", "/forecast/latest", "/forecast/latest", {}, marks=WAITS_FOR_ROLE_5),
    ("post", "/forecast/recompute", "/forecast/recompute", {}),
    ("post", "/forecast/events", "/forecast/events",
     {"json": {"label": "Server repair", "date_from": "2026-12-02", "date_to": "2026-12-02", "effect": "extra_outflow",
               "amount": {"amount": "2000.00", "currency": "PLN"}}}),
    ("post", "/forecast/scenario", "/forecast/scenario",
     {"json": {"credit_line": {"limit": {"amount": "30000.00", "currency": "PLN"}, "from": "2026-11-28"}}}),
]
STATUS = {"/forecast/events": 201}


@pytest.fixture
def api(labs_db, db_url):  # noqa: F811
    with TestClient(create_app(database_url=db_url)) as client:
        yield client


def borsuk(client, method, url, **kw):
    return getattr(client, method)(f"/api/v1{url}", params={"company_id": "co_borsuk"}, **kw)


@pytest.mark.parametrize("method, template, url, request_kw", PATHS,
                         ids=["GET /ledger", "GET /ledger/summary", "GET /forecast/latest", "POST /forecast/recompute",
                              "POST /forecast/events", "POST /forecast/scenario"])
def test_each_path_answers_with_engine_data_that_validates(api, method, template, url, request_kw):
    response = borsuk(api, method, url, **request_kw)
    assert response.status_code == STATUS.get(template, 200), response.text
    schema = contract.response_schema(method, template, response.status_code)
    assert contract.errors(response.json(), schema) == []


def test_forecast_by_id_and_export(api):
    forecast = borsuk(api, "post", "/forecast/recompute").json()
    by_id = api.get(f"/api/v1/forecast/{forecast['id']}")
    assert by_id.status_code == 200 and by_id.json()["inputs_hash"] == forecast["inputs_hash"]
    assert contract.errors(by_id.json(), contract.response_schema("get", "/forecast/{id}", 200)) == []
    export = borsuk(api, "get", "/ledger/export")
    assert export.status_code == 200 and export.content[:2] == b"PK"


def test_latest_is_the_engines_forecast_even_after_a_fixture_from_the_future(labs_db):  # noqa: F811
    fixture = read("forecast")[0]
    Store(labs_db).add("forecast", fixture, company_id="co_borsuk")

    forecast = engine.latest(labs_db, "co_borsuk")

    assert forecast["id"] != fixture["id"]
    assert engine.latest_base(labs_db, "co_borsuk")["id"] == forecast["id"]
    assert engine.latest(labs_db, "co_borsuk")["id"] == forecast["id"]
    assert all(c["evidence"] for c in forecast["components"])


def test_latest_components_each_carry_evidence(api):
    borsuk(api, "post", "/forecast/recompute")
    latest = borsuk(api, "get", "/forecast/latest").json()
    assert latest["method"] == "recurring-schedule + weekday-average v1"
    assert latest["components"] and all(c["evidence"] for c in latest["components"])


def test_ledger_kpis(labs_db):  # noqa: F811
    s = Store(labs_db)
    expense = {"id": "led_vat", "company_id": "co_borsuk", "date": "2026-11-20", "type": "expense",
               "category": "equipment", "status": "approved", "amount": {"amount": "-1299.00", "currency": "PLN"},
               "amount_base": {"amount": "-1299.00", "currency": "PLN"},
               "vat": {"amount": {"amount": "242.90", "currency": "PLN"}, "deductible": False, "reason": "no NIP"},
               "paid_by": "employee_private", "explanation": "test", "evidence": []}
    s.put("ledger_entry", expense, company_id="co_borsuk")
    s.put("ledger_entry", {**expense, "id": "led_vat_2025", "date": "2025-12-30"}, company_id="co_borsuk")

    kpis = engine.ledger_kpis(labs_db, "co_borsuk")

    assert kpis["vat_lost_ytd"] == {"amount": "242.90", "currency": "PLN"}
    assert kpis["reimbursements_owed"] == {"amount": "5169.00", "currency": "PLN"}
    forecast = engine.latest(labs_db, "co_borsuk")
    taxes = Decimal(0)
    for c in forecast["components"]:
        if c["kind"] in ("tax", "social_security"):
            each = Decimal(c["amount_base"]["amount"]) / len(c["dates"])
            taxes += each * sum(1 for d in c["dates"] if "2026-11-21" < d <= "2026-12-21")
    assert kpis["tax_due_next_30d"] == {"amount": f"{abs(taxes):.2f}", "currency": "PLN"}
    assert abs(taxes) == Decimal("33899.33")
    schema = contract.response_schema("get", "/ledger/summary", 200)["properties"]["kpis"]
    assert contract.errors(kpis, schema) == []


@pytest.mark.skipif(PIZZERIA_CSV is None, reason="pizzeria CSV not present (git-ignored event material)")
def test_closing_the_pizzeria_in_june_through_the_api_moves_the_low_to_minus_22_8k(db, db_url):
    seed(db)
    s = Store(db)
    account = {"id": "acc_pizzeria", "company_id": "co_amalfi", "kind": "company_bank", "currency": "EUR",
               "include_in_liquidity": True, "balance": {"amount": "33266.35", "currency": "EUR"},
               "balance_at": "2025-12-31T23:59:59Z"}
    s.put("account", account, company_id="co_amalfi")
    for t in bank_lines(PIZZERIA_CSV, account):
        s.add("transaction", t, company_id="co_amalfi")
    with TestClient(create_app(database_url=db_url)) as client:
        before = client.post("/api/v1/forecast/recompute", params={"company_id": "co_amalfi"}).json()
        event = {k: CLOSED_JUNE[k] for k in ("label", "date_from", "date_to", "effect")}
        after = client.post("/api/v1/forecast/events", params={"company_id": "co_amalfi"}, json=event)

    assert after.status_code == 201
    low = after.json()["min_balance"]
    assert Decimal(before["min_balance"]["amount"]["amount"]) > Decimal("-5000")
    assert low["date"] == "2025-07-03"
    assert low["amount"]["amount"] == "-22813.26"
    assert json.dumps(after.json()).count('"evidence": []') == 0
