"""Seam: FX Shield on open foreign-currency invoices -> downside, hedge terms and the company's own figures."""
import json
from datetime import date

import pytest

from backend.api import contract
from backend.finance import engine, fx, settings
from backend.finance.forecast import build_forecast

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


def shares(a):
    return {r["id"]: r["loss_share_percent"] for r in a["loss_vs_references"]}


@pytest.fixture(scope="module")
def labs():
    return borsuk()


@pytest.fixture(scope="module")
def labs_forecast(labs):
    return build_forecast(**labs)


def assess_all(inputs, forecast, items=None):
    if items is not None:
        inputs = {**inputs, "open_items": items}
    found = fx.assess_company(inputs, {"EUR": HISTORY["EUR"], "USD": HISTORY["USD"]}, forecast)
    return {a["document_id"]: a for a in found}


def test_three_years_of_nbp_rates_end_the_day_before_the_as_of_date():
    for currency in ("EUR", "USD"):
        h = fx.history_window(HISTORY[currency], AS_OF)
        assert (len(h), h[0][0].isoformat(), h[-1][0].isoformat()) == (756, "2023-11-21", "2026-11-20")
    assert (HISTORY["USD"]["2026-11-20"], HISTORY["EUR"]["2026-11-20"]) == ("4.0613", "4.4559")


def test_the_company_facts_are_month_by_month_because_money_in_varies(labs, labs_forecast):
    facts = fx.company_facts(labs, labs_forecast)
    assert [m["month"] for m in facts["months"]] == [f"2026-{m:02d}" for m in range(1, 11)]  # full months only
    assert (facts["months"][8]["money_in"], facts["months"][9]["money_in"]) == (pln("60147.00"), pln("149478.00"))
    assert facts["money_in_strongest_month"] == pln("167845.50")
    assert {r["id"]: r["amount"] for r in facts["references"]} == {
        "money_in_weakest_month": pln("60147.00"), "money_in_median_month": pln("116005.50"),
        "money_out_median_month": pln("118288.61"), "cash_today": pln("38401.15")}
    assert facts["lowest_forecast_balance"] == {"date": "2026-12-04", "amount": pln("-13178.34")}
    assert [t for t in labs["transactions"] if t.get("transaction_type") == "internal"]  # own transfers: not counted


def test_lakeshore_facts(labs, labs_forecast):
    a = assess_all(labs, labs_forecast)[LAKESHORE]
    assert (a["status"], a["expected_cash_date"], a["horizon_days"], a["scenarios"]) == ("open", "2027-01-05", 45, 724)
    assert a["value_today_base"] == pln("162452.00")
    assert (a["bad_case_p95"], a["expected_shortfall"]) == (pln("-6373.91"), pln("-6594.83"))
    assert (a["good_case_p95"], a["average_result"]) == (pln("7732.83"), pln("18.63"))
    assert shares(a) == {"money_in_weakest_month": "11.0", "money_in_median_month": "5.7",
                         "money_out_median_month": "5.6", "cash_today": "17.2"}
    assert a["lowest_balance_after_payment"] == {"date": "2027-01-05", "balance": pln("158250.52")}
    assert a["lowest_balance_after_payment_with_bad_case"]["balance"] == pln("151655.69")
    assert (a["already_negative_after_payment"], a["bad_case_takes_balance_below_zero"]) == (False, False)
    assert a["hedge"] == {"ratio": "1.0", "value_date": "2027-01-05", "notional": {"amount": "40000.00", "currency": "USD"},
                          "sell_currency": "USD", "buy_currency": "PLN", "forward_rate": "4.0491",
                          "forward_cost": pln("487.36"), "option_cost": pln("1949.42"), "with_forward": pln("161964.64")}
    assert not any(word in key for key in a for word in ("profit", "verdict", "threshold"))


def test_nordwind_facts_paid_in_16_days_into_a_forecast_already_below_zero(labs, labs_forecast):
    a = assess_all(labs, labs_forecast)[NORDWIND]
    assert (a["status"], a["expected_cash_date"], a["horizon_days"], a["scenarios"]) == ("open", "2026-12-07", 16, 745)
    assert (a["value_today_base"], a["expected_shortfall"]) == (pln("81144.00"), pln("-994.46"))
    assert shares(a) == {"money_in_weakest_month": "1.7", "money_in_median_month": "0.9",
                         "money_out_median_month": "0.8", "cash_today": "2.6"}
    assert a["lowest_balance_after_payment"] == {"date": "2027-01-04", "balance": pln("-2473.48")}
    assert a["lowest_balance_after_payment_with_bad_case"]["balance"] == pln("-3467.94")
    assert (a["already_negative_after_payment"], a["bad_case_takes_balance_below_zero"]) == (True, True)
    assert (a["hedge"]["ratio"], a["hedge"]["value_date"], a["hedge"]["notional"]) == \
        ("0.8", "2026-12-07", {"amount": "14720.00", "currency": "EUR"})  # a late client: 80% on the expected date


def test_a_large_euro_purchase(labs, labs_forecast):
    a = assess_all(labs, labs_forecast, [item("doc_salami", "payable", "200000.00", "EUR", "2027-01-20")])["doc_salami"]
    assert (a["horizon_days"], a["scenarios"]) == (60, 713)
    assert (a["covered"], a["net_amount"]) == ({"amount": "3100.00", "currency": "EUR"},
                                               {"amount": "196900.00", "currency": "EUR"})  # the EUR account pays part
    assert (a["expected_shortfall"], shares(a)["money_in_weakest_month"]) == (pln("-19254.93"), "32.0")
    assert (a["hedge"]["sell_currency"], a["hedge"]["buy_currency"], a["hedge"]["forward_rate"]) == ("PLN", "EUR", "4.4232")


def test_euro_bills_due_near_a_euro_invoice_hedge_it_for_free(labs, labs_forecast):
    found = assess_all(labs, labs_forecast, [item("doc_r", "receivable", "18400.00", "EUR", "2026-12-10"),
                                             item("doc_p", "payable", "18000.00", "EUR", "2026-12-18")])
    assert {k: v["status"] for k, v in found.items()} == {"doc_r": "naturally_hedged", "doc_p": "naturally_hedged"}
    assert found["doc_r"]["net_amount"] == {"amount": "400.00", "currency": "EUR"}


def test_a_small_bill_is_measured_like_any_other_the_model_judges_whether_it_matters(labs, labs_forecast):
    a = assess_all(labs, labs_forecast, [item("doc_saas", "payable", "45.00", "USD", "2026-12-01")])["doc_saas"]
    assert (a["status"], a["expected_shortfall"], shares(a)["money_in_weakest_month"]) == ("open", pln("-4.33"), "0.0")


def test_a_company_with_another_base_currency_and_no_history_is_assessed_by_the_same_code():
    inputs = {"company": {"id": "co_other", "base_currency": "EUR", "as_of_date": "2026-11-21", "country": "PL"},
              "accounts": [{"id": "acc", "currency": "EUR", "include_in_liquidity": True,
                            "opening_balance": {"amount": "50000.00", "currency": "EUR"}}],
              "transactions": [], "rates": {"EUR": "1", "USD": "0.9114"},
              "open_items": [item("doc_us", "receivable", "40000.00", "USD", "2027-01-05")]}
    histories = {"USD": engine.fx_history(None, "USD", "EUR", AS_OF)}  # cross rates from the NBP PLN rates
    (a,) = fx.assess_company(inputs, histories, build_forecast(**inputs))
    assert (a["value_today_base"], a["horizon_days"], a["scenarios"]) == ({"amount": "36456.00", "currency": "EUR"}, 45, 724)
    assert (a["hedge"]["sell_currency"], a["hedge"]["buy_currency"], a["hedge"]["forward_rate"]) == ("USD", "EUR", "0.9087")
    assert a["company"]["months"] == []  # no bank lines yet: the only reference is the cash held
    assert [r["id"] for r in a["loss_vs_references"]] == ["cash_today"]


def test_no_fixed_threshold_of_large_exists_in_the_settings():
    names = [n for n in dir(settings) if n.startswith("FX_")]
    assert not [n for n in names if any(w in n for w in ("FALLBACK", "FLOOR", "PROFIT", "LOSS_LIMIT", "MENTION", "CARD"))]


def test_the_engine_assesses_borsuk_labs_from_the_database(labs_db):  # noqa: F811
    found = {a["document_id"]: a for a in engine.fx_assessments(labs_db, "co_borsuk")}
    assert {k: (a["status"], a["expected_shortfall"]) for k, a in found.items()} == {
        LAKESHORE: ("open", pln("-6594.83")), NORDWIND: ("open", pln("-994.46"))}
    assert shares(found[LAKESHORE])["money_in_weakest_month"] == "11.0"


def test_fx_exposure_matches_the_contract_and_has_no_verdict_before_fx_shield_judged(labs_db):  # noqa: F811
    body = engine.fx_exposure(labs_db, "co_borsuk")
    assert contract.errors(body, contract.response_schema("get", "/fx/exposure", 200)) == []
    assert {i["document_id"] for i in body["items"]} == {NORDWIND, LAKESHORE}
    assert all("verdict" not in i and i["recommendation_id"] is None for i in body["items"])


def book_forward(db, rate=None):
    """Lakeshore's forward as the Sandbox Bank booked it: an executed fx_hedge card and its (possibly edited) approval."""
    from backend.db.store import Store
    s = Store(db)
    s.put("approval", {"id": "apr_fx", "subject_type": "recommendation", "subject_id": "rec_fx_lake",
                       "decision": "approved_with_changes" if rate else "approved",
                       "changes": {"proposed_action.params.rate": rate} if rate else None,
                       "execution": {"mode": "simulated", "status": "done", "reference": "SIM-FX-0001"}},
          company_id="co_borsuk")
    s.put("recommendation", {"id": "rec_fx_lake", "company_id": "co_borsuk", "agent": "fx", "type": "fx_hedge",
                             "status": "executed_simulated", "created_at": "2026-11-21T10:15:03Z",
                             "approval_id": "apr_fx", "subject": {"kind": "document", "id": LAKESHORE, "label": "x"},
                             "proposed_action": {"kind": "book_fx_forward",
                                                 "params": {"rate": "4.0491", "hedge_ratio": 1.0}}})
    db.commit()


def lakeshore_component(db):
    inputs = engine.load_inputs(db, "co_borsuk")
    return next(c for c in build_forecast(**inputs)["components"] if c["id"] == f"c_{LAKESHORE}")


def test_an_executed_forward_values_the_invoice_at_its_rate_and_marks_it_hedged(labs_db):  # noqa: F811
    book_forward(labs_db)
    c = lakeshore_component(labs_db)
    assert ("at the forward rate 4.0491 (SIM-FX-0001)" in c["schedule"], c["amount_base"]) == (True, pln("161964.00"))
    found = {a["document_id"]: a for a in engine.fx_assessments(labs_db, "co_borsuk")}
    assert (found[LAKESHORE]["status"], found[NORDWIND]["status"]) == ("hedged", "open")
    item = {i["document_id"]: i for i in engine.fx_exposure(labs_db, "co_borsuk")["items"]}[LAKESHORE]
    assert item["verdict"] == "hedged"


def test_the_rate_the_owner_approved_is_the_one_that_counts(labs_db):  # noqa: F811
    book_forward(labs_db, rate="4.0300")
    c = lakeshore_component(labs_db)
    assert ("at the forward rate 4.0300 (SIM-FX-0001)" in c["schedule"], c["amount_base"]) == (True, pln("161200.00"))
