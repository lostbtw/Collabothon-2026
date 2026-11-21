"""Regression: the demo numbers (#45). Pure, no database.

If one of these fails, the demo script changes, not the engine (spec #4, risk R15). The values are the engine's own
output at the time of writing; the human decided on 21 Nov 2026 that the script follows them.

Borsuk Labs runs everywhere (role 4's committed scenario). Pizzeria Amalfi needs the organisers' CSV, which is
git-ignored event material (hard rule 2: no real data in the repo); without it those tests skip and say where to put it.
"""
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
    """Pizzeria Amalfi's real balance at the end of each booking day: 2,500.00 EUR opening (not in the file) plus
    every bank line in the base currency, so the 12 CHF lines booked in the EUR account count in EUR."""
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
    end_of_june = max(day for day in pizzeria_days if day <= "2025-06-30")  # closed in June: no line on the 30th
    assert pizzeria_days[end_of_june] == Decimal("-20098.69")


def test_borsuk_labs_is_lowest_on_4_december_at_minus_12_970_34_pln(labs_forecast):
    assert labs_forecast["min_balance"] == {"date": "2026-12-04", "amount": pln("-12970.34")}
    assert labs_forecast["first_negative_date"] == "2026-11-30"


def test_borsuk_labs_stress_case_is_minus_46_072_20_pln_and_the_credit_line_50_000_pln(labs_forecast):
    assert (STRESS_EXTRA_DAYS, SIZING_STEP) == (14, Decimal("5000"))  # the settings the numbers below assume
    stress = stress_of(labs_forecast)
    assert (stress["label"], stress["date"], stress["balance"]) == \
        ("Nordwind pays 21 Dec", "2026-12-21", pln("-46072.20"))
    assert credit_line_size(labs_forecast)["limit"] == pln("50000.00")
