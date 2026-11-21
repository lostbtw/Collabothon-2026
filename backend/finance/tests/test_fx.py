"""Seam: FX Shield (#47): open foreign-currency invoices -> downside, profit, verdict and hedge terms.
Pure, plus the engine on the test database. Rates: backend/finance/data/nbp_history_3y.json (NBP table A, 3 years)."""
import json
from datetime import date
from decimal import Decimal

import pytest

from backend.api import contract
from backend.finance import engine, fx
from backend.finance.settings import FX_LOSS_LIMIT_PLN

from .data import borsuk
from .test_engine import labs_db  # noqa: F401  (fixture: Borsuk Labs in the database)

HISTORY = json.loads(engine.FX_HISTORY_FILE.read_text(encoding="utf-8"))
AS_OF = date(2026, 11, 21)
LAKESHORE, NORDWIND = "doc_fv_2026_11_045", "doc_fv_2026_10_044"


def pln(amount):
    return {"amount": amount, "currency": "PLN"}


def item(id_, kind, amount, currency, due, delay=0):
    return {"id": id_, "kind": kind, "label": f"Invoice {id_}", "key": id_,
            "amount": {"amount": amount, "currency": currency}, "due_date": due, "delay_days": delay}


@pytest.fixture(scope="module")
def labs():
    return borsuk()


def assess_all(inputs, owner_profits=None, items=None):
    if items is not None:
        inputs = {**inputs, "open_items": items}
    found = fx.assess_company(inputs, {"EUR": HISTORY["EUR"], "USD": HISTORY["USD"]}, owner_profits or {},
                              FX_LOSS_LIMIT_PLN)
    return {a["document_id"]: a for a in found}


def test_three_years_of_nbp_rates_end_the_day_before_the_as_of_date():
    for currency in ("EUR", "USD"):
        h = fx.history_window(HISTORY[currency], AS_OF)
        assert (len(h), h[0][0].isoformat(), h[-1][0].isoformat()) == (756, "2023-11-21", "2026-11-20")
    assert (HISTORY["USD"]["2026-11-20"], HISTORY["EUR"]["2026-11-20"]) == ("4.0613", "4.4559")


def test_lakeshore_would_lose_82_percent_of_its_profit_so_a_forward_is_proposed(labs):
    a = assess_all(labs, {LAKESHORE: pln("8000.00")})[LAKESHORE]
    assert (a["expected_cash_date"], a["horizon_days"], a["scenarios"]) == ("2027-01-05", 45, 724)
    assert a["value_today_base"] == pln("162452.00")
    assert (a["bad_case_p95"], a["expected_shortfall"]) == (pln("-6373.91"), pln("-6594.83"))
    assert (a["good_case_p95"], a["average_result"]) == (pln("7732.83"), pln("18.63"))
    assert (a["deal_profit"], a["profit_source"], a["share_of_profit"]) == (pln("8000.00"), "owner", "0.8244")
    assert (a["verdict"], a["mention"]) == ("hedge_proposed", True)
    assert a["hedge"] == {"ratio": "1.0", "value_date": "2027-01-05", "notional": {"amount": "40000.00", "currency": "USD"},
                          "sell_currency": "USD", "buy_currency": "PLN", "forward_rate": "4.0491",
                          "forward_cost": pln("487.36"), "option_cost": pln("1949.42"), "with_forward": pln("161964.64")}


def test_nordwind_paid_in_16_days_is_not_worth_hedging(labs):
    a = assess_all(labs)[NORDWIND]
    assert (a["expected_cash_date"], a["horizon_days"], a["scenarios"]) == ("2026-12-07", 16, 745)
    assert a["value_today_base"] == pln("81144.00")
    assert (a["bad_case_p95"], a["expected_shortfall"]) == (pln("-931.94"), pln("-994.46"))
    assert (a["deal_profit"], a["profit_source"], a["share_of_profit"]) == (pln("13794.48"), "average_margin", "0.0721")
    assert a["profit_note"].startswith("default margin 17% from the settings")
    assert (a["verdict"], a["mention"]) == ("not_worth_it", True)
    assert (a["hedge"]["ratio"], a["hedge"]["value_date"], a["hedge"]["notional"]) == \
        ("0.8", "2026-12-07", {"amount": "14720.00", "currency": "EUR"})  # a late client: 80% on the expected date


def test_a_large_euro_purchase_has_no_profit_and_is_compared_with_the_loss_limit(labs):
    a = assess_all(labs, items=[item("doc_salami", "payable", "200000.00", "EUR", "2027-01-20")])["doc_salami"]
    assert (a["horizon_days"], a["scenarios"]) == (60, 713)
    assert (a["covered"], a["net_amount"]) == ({"amount": "3100.00", "currency": "EUR"},
                                               {"amount": "196900.00", "currency": "EUR"})  # the EUR account pays part
    assert a["expected_shortfall"] == pln("-19254.93")
    assert (a["deal_profit"], a["profit_source"], a["verdict"]) == (None, "loss_limit", "hedge_proposed")
    assert (a["hedge"]["sell_currency"], a["hedge"]["buy_currency"], a["hedge"]["forward_rate"]) == ("PLN", "EUR", "4.4232")


def test_euro_bills_due_near_a_euro_invoice_hedge_it_for_free(labs):
    found = assess_all(labs, items=[item("doc_r", "receivable", "18400.00", "EUR", "2026-12-10"),
                                    item("doc_p", "payable", "18000.00", "EUR", "2026-12-18")])
    assert {k: v["verdict"] for k, v in found.items()} == {"doc_r": "naturally_hedged", "doc_p": "naturally_hedged"}
    assert found["doc_r"]["net_amount"] == {"amount": "400.00", "currency": "EUR"}


def test_a_small_dollar_bill_is_assessed_but_not_worth_a_card(labs):
    a = assess_all(labs, items=[item("doc_saas", "payable", "45.00", "USD", "2026-12-01")])["doc_saas"]
    assert (a["verdict"], a["mention"]) == ("not_worth_it", False)


def test_a_forward_that_costs_more_than_half_the_possible_loss_is_not_worth_it():
    assert fx.verdict(Decimal("100"), None, Decimal("50"), Decimal("51"))[0] == "not_worth_it"
    assert fx.verdict(Decimal("100"), None, Decimal("50"), Decimal("50"))[0] == "hedge_proposed"


def test_the_average_margin_comes_from_categorised_bank_lines_or_from_the_settings(labs):
    lines = ([{"booking_date": f"2026-{m:02d}-10", "category": "revenue_services", "amount_base": pln("10000.00")}
              for m in range(1, 12)]
             + [{"booking_date": f"2026-{m:02d}-15", "category": "salaries", "amount_base": pln("-8000.00")}
                for m in range(1, 12)]
             + [{"booking_date": f"2026-{m:02d}-16", "category": "owner_private", "amount_base": pln("-500.00")}
                for m in range(1, 12)])
    assert fx.average_margin(lines, AS_OF)[0] == Decimal("0.2")  # the owner's private spending is not a business cost
    margin, note = fx.average_margin(labs["transactions"], AS_OF)  # the test bank lines carry no category
    assert margin == Decimal("0.17") and "too few categorised" in note
    losing = [dict(t, amount_base=pln("-20000.00")) if t["category"] == "salaries" else t for t in lines]
    assert fx.average_margin(losing, AS_OF)[0] == Decimal("0.17")  # a negative margin is no basis for a profit


def test_the_engine_assesses_borsuk_labs_from_the_database(labs_db):  # noqa: F811
    found = {a["document_id"]: a for a in engine.fx_assessments(labs_db, "co_borsuk")}
    assert set(found) == {NORDWIND, LAKESHORE}
    assert (found[LAKESHORE]["profit_source"], found[LAKESHORE]["verdict"]) == ("owner", "hedge_proposed")
    assert found[LAKESHORE]["expected_shortfall"] == pln("-6594.83")
    assert (found[NORDWIND]["verdict"], found[NORDWIND]["expected_shortfall"]) == ("not_worth_it", pln("-994.46"))


def test_fx_exposure_matches_the_contract(labs_db):  # noqa: F811
    body = engine.fx_exposure(labs_db, "co_borsuk")
    assert contract.errors(body, contract.response_schema("get", "/fx/exposure", 200)) == []
    assert {i["document_id"]: i["verdict"] for i in body["items"]} == {NORDWIND: "not_worth_it", LAKESHORE: "hedge_proposed"}
    assert all(i["recommendation_id"] is None for i in body["items"])  # no cards yet (plan 004)
