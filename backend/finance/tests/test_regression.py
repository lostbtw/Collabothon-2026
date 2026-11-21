"""Regression: the demo numbers; if one fails, the demo script changes, not the engine (the pizzeria needs its CSV)."""
from collections import defaultdict
from decimal import Decimal

import pytest

from backend.finance.forecast import build_forecast
from backend.finance.scenarios import credit_line_size, stress_of
from backend.finance.settings import SIZING_STEP, STRESS_EXTRA_DAYS

from .data import DEFAULT_CSV, PIZZERIA_CSV, SCENARIO, borsuk, pizzeria

needs_csv = pytest.mark.skipif(
    PIZZERIA_CSV is None,
    reason=f"pizzeria CSV not present (git-ignored event material, shared out of band): put it at {DEFAULT_CSV} "
           f"or {SCENARIO / DEFAULT_CSV.name}")


def pln(amount: str) -> dict:
    return {"amount": amount, "currency": "PLN"}


@pytest.fixture(scope="module")
def labs_forecast():
    return build_forecast(**borsuk())


@pytest.fixture(scope="module")
def pizzeria_days():
    data = pizzeria()
    by_day: dict[str, Decimal] = defaultdict(Decimal)
    for t in data["transactions"]:
        by_day[t["booking_date"]] += Decimal(t["amount_base"]["amount"])
    balance = Decimal(data["accounts"][0]["opening_balance"]["amount"])
    days = {}
    for day in sorted(by_day):
        balance += by_day[day]
        days[day] = balance
    return days


@needs_csv
def test_pizzeria_ends_2025_at_33_266_35_eur(pizzeria_days):
    last = max(pizzeria_days)
    assert (last, pizzeria_days[last]) == ("2025-12-31", Decimal("33266.35"))


@needs_csv
def test_pizzeria_is_lowest_on_3_july_2025_at_minus_22_097_60_eur(pizzeria_days):
    low = min(pizzeria_days, key=pizzeria_days.get)
    assert (low, pizzeria_days[low]) == ("2025-07-03", Decimal("-22097.60"))
    end_of_june = max(day for day in pizzeria_days if day <= "2025-06-30")
    assert pizzeria_days[end_of_june] == Decimal("-20098.69")


def test_borsuk_labs_is_lowest_on_4_december_at_minus_13_178_34_pln(labs_forecast):
    assert labs_forecast["min_balance"] == {"date": "2026-12-04", "amount": pln("-13178.34")}
    assert labs_forecast["first_negative_date"] == "2026-11-30"


def test_borsuk_labs_stress_case_is_minus_45_497_99_pln_and_the_credit_line_50_000_pln(labs_forecast):
    assert (STRESS_EXTRA_DAYS, SIZING_STEP) == (14, Decimal("5000"))
    stress = stress_of(labs_forecast)
    assert (stress["label"], stress["date"], stress["balance"]) == \
        ("Nordwind pays 21 Dec", "2026-12-21", pln("-45497.99"))
    assert credit_line_size(labs_forecast)["limit"] == pln("50000.00")
