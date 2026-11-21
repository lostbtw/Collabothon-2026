"""Seam: alerts, what-if scenarios, stress case and credit-line sizing. Pure, plus the engine on the test DB."""
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import contract
from backend.api.app import create_app
from backend.db.contracts import Forecast
from backend.finance import engine
from backend.finance.forecast import build_forecast
from backend.finance.scenarios import credit_line_size, stress_of, with_changes
from backend.finance.settings import SIZING_STEP, STRESS_EXTRA_DAYS

from .data import borsuk
from .test_engine import labs_db  # noqa: F401  (fixture: Borsuk Labs in the database)


@pytest.fixture(scope="module")
def base():
    return build_forecast(**borsuk())


def balance(f, day):
    return Decimal(next(p for p in f["points"] if p["date"] == day)["balance"])


def low(f):
    return Decimal(f["min_balance"]["amount"]["amount"])


def test_the_cash_gap_alert_names_its_dates_and_size(base):
    (gap,) = [a for a in base["alerts"] if a["type"] == "cash_gap"]
    assert gap["date_from"] == "2026-11-30" and gap["date_to"] == "2026-12-06"
    assert Decimal(gap["max_shortfall"]["amount"]) == -low(base)
    assert gap["severity"] == "critical" and gap["days_ahead"] == 9


def test_the_stress_case_is_the_late_client_paying_14_days_later(base):
    s = stress_of(base)
    assert STRESS_EXTRA_DAYS == 14
    assert s["label"] == "Nordwind pays 21 Dec" and s["date"] == "2026-12-21"
    assert Decimal(s["balance"]["amount"]) < low(base)
    nordwind = next(c for c in base["components"] if c["id"] == s["receivable_component_id"])
    arrival_day_before_the_money = balance(base, "2026-12-21") - Decimal(nordwind["amount_base"]["amount"])
    assert Decimal(s["balance"]["amount"]) == arrival_day_before_the_money


def test_the_credit_line_covers_the_worst_case_rounded_up(base):
    sizing = credit_line_size(base)
    shortfall = -Decimal(sizing["stress"]["balance"]["amount"])
    limit = Decimal(sizing["limit"]["amount"])
    assert sizing["basis"] == "stress case"
    assert Decimal(sizing["shortfall"]["amount"]) == shortfall
    assert limit >= shortfall and limit - shortfall < SIZING_STEP and limit % SIZING_STEP == 0


def test_a_25000_credit_line_keeps_the_forecast_above_zero(base):
    what_if = with_changes(base, {"credit_line": {"limit": {"amount": "25000.00", "currency": "PLN"},
                                                  "from": base["as_of_date"]}})
    assert low(what_if) > 0 and what_if["first_negative_date"] is None
    assert not any(a["type"] == "cash_gap" for a in what_if["alerts"])
    assert low(base) < 0
    Forecast.model_validate({**what_if, "scenario_of": base["id"]})


def test_shifting_a_receivable_moves_its_money_between_the_dates(base):
    nordwind = next(c for c in base["components"] if c["kind"] == "known_receivable" and "Nordwind" in c["label"])
    document_id = next(e["id"] for e in nordwind["evidence"] if e["kind"] == "document")
    amount = Decimal(nordwind["amount_base"]["amount"])

    moved = with_changes(base, {"shift_receivable": {"document_id": document_id, "new_date": "2026-12-21"}})

    assert balance(moved, "2026-12-07") == balance(base, "2026-12-07") - amount
    assert balance(moved, "2026-12-20") == balance(base, "2026-12-20") - amount
    assert balance(moved, "2026-12-21") == balance(base, "2026-12-21")
    assert low(moved) < low(base)


def test_shifting_a_payable_raises_the_balance_until_its_new_date(base):
    vat = next(c for c in base["components"] if c["kind"] == "tax" and "2026-11-25" in c["dates"])
    first = Decimal(vat["amount_base"]["amount"]) / len(vat["dates"])

    moved = with_changes(base, {"shift_payable": {"component_id": vat["id"], "days": 7}})

    assert balance(moved, "2026-11-25") == balance(base, "2026-11-25") - first
    assert balance(moved, "2026-12-02") == balance(base, "2026-12-02")
    assert "2026-12-02" in next(c for c in moved["components"] if c["id"] == vat["id"])["dates"]


def test_without_a_late_client_the_stress_case_is_the_forecast_itself(base):
    on_time = {**base, "components": [c for c in base["components"] if c["kind"] != "known_receivable"]}
    s = stress_of(on_time)
    assert s["receivable_component_id"] is None and s["balance"] == base["min_balance"]["amount"]


def test_the_engine_gives_the_stress_case_and_the_credit_line_from_the_database(labs_db):  # noqa: F811
    forecast = engine.recompute(labs_db, "co_borsuk")
    s = engine.stress(labs_db, "co_borsuk")
    line = engine.credit_line(labs_db, "co_borsuk")
    assert s == stress_of(forecast) and s["label"] == "Nordwind pays 21 Dec"
    assert line["limit"] == credit_line_size(forecast)["limit"]
    assert forecast["safety_buffer"] is not None


def test_the_scenario_endpoint_shifts_a_receivable_and_validates(labs_db, db_url):  # noqa: F811
    with TestClient(create_app(database_url=db_url)) as client:
        client.post("/api/v1/forecast/recompute", params={"company_id": "co_borsuk"})
        body = {"shift_receivable": {"document_id": "doc_fv_2026_10_044", "new_date": "2026-12-21"}}
        response = client.post("/api/v1/forecast/scenario", params={"company_id": "co_borsuk"}, json=body)
    assert response.status_code == 200
    assert contract.errors(response.json(), contract.response_schema("post", "/forecast/scenario", 200)) == []
    assert response.json()["scenario_of"] and "Nordwind" in " ".join(response.json()["assumptions"])


def test_the_engine_has_no_company_hardcoded():
    finance = Path(__file__).resolve().parents[1]
    for path in finance.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"co_borsuk|co_amalfi|Nordwind|Borsuk|Amalfi", text), path.name
