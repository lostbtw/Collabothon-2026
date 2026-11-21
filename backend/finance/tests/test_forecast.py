"""Seam: bank lines + open invoices + Ledger + owner events -> Forecast. Pure, no database."""
from decimal import Decimal

import pytest

from backend.db.contracts import Forecast
from backend.finance.forecast import build_forecast, recurring_series_ids

from .data import CLOSED_JUNE, PIZZERIA_CSV, borsuk, pizzeria

needs_csv = pytest.mark.skipif(PIZZERIA_CSV is None, reason="pizzeria CSV not present (git-ignored event material)")


def point(forecast, day):
    return next(p for p in forecast["points"] if p["date"] == day)


def amount(m):
    return Decimal(m["amount"])


@pytest.fixture(scope="module")
def pizza():
    return pizzeria() if PIZZERIA_CSV else None


@pytest.fixture(scope="module")
def labs():
    return borsuk()


@needs_csv
def test_pizzeria_on_15_may_with_the_june_closure_predicts_the_july_gap(pizza):
    assert len(pizza["transactions"]) == 1125  # the whole year is ingested; only lines up to 15 May are used
    forecast = build_forecast(**pizza, events=[CLOSED_JUNE], horizon_days=60)

    low = forecast["min_balance"]
    # Polish tax rules for every company: the pizzeria no longer matches its German history
    assert (low["date"], amount(low["amount"])) == ("2025-07-03", Decimal("-22813.26"))
    Forecast.model_validate(forecast)


@needs_csv
def test_pizzeria_without_the_event_misses_the_gap(pizza):
    with_event = build_forecast(**pizza, events=[CLOSED_JUNE], horizon_days=60)
    forecast = build_forecast(**pizza, horizon_days=60)
    assert amount(forecast["min_balance"]["amount"]) - amount(with_event["min_balance"]["amount"]) >= Decimal("10000.00")


@needs_csv
def test_the_tax_office_is_split_into_its_separate_series(pizza):
    ids = recurring_series_ids(**{k: pizza[k] for k in ("company", "accounts", "transactions", "rates")})
    tax_office = {ids[t["id"]] for t in pizza["transactions"]
                  if t["id"] in ids and "Tax Office" in (t["counterparty_name_raw"] or "")}
    assert len(tax_office) >= 2  # monthly wage tax and quarterly trade tax are separate series


def test_borsuk_labs_cash_gap_from_30_november(labs):
    forecast = build_forecast(**labs)

    assert forecast["opening_balance"] == {"amount": "38401.15", "currency": "PLN"}  # 24,730.15 + 3,100 EUR x 4.41
    assert forecast["first_negative_date"] == "2026-11-30"
    (gap,) = forecast["alerts"]
    assert gap["type"] == "cash_gap" and gap["severity"] == "critical" and gap["date_from"] == "2026-11-30"
    low = forecast["min_balance"]
    assert "2026-12-01" <= low["date"] <= "2026-12-06"
    assert Decimal("-16000") < amount(low["amount"]) < Decimal("-9000")
    at_low = point(forecast, low["date"])
    assert Decimal(at_low["low"]) < amount(low["amount"]) < Decimal(at_low["high"])  # the band surrounds the line
    widths = [Decimal(p["high"]) - Decimal(p["low"]) for p in forecast["points"]]
    assert widths[0] == 0 and widths == sorted(widths)  # no uncertainty today, more every day after
    Forecast.model_validate(forecast)


def test_borsuk_labs_components_carry_the_story_items(labs):
    forecast = build_forecast(**labs)
    by_kind = {}
    for c in forecast["components"]:
        by_kind.setdefault(c["kind"], []).append(c)

    (nordwind,) = [c for c in by_kind["known_receivable"] if "Nordwind" in c["label"]]
    assert nordwind["amount_base"]["amount"] == "81144.00" and nordwind["dates"] == ["2026-12-07"]
    assert "average delay of 23 days" in nordwind["schedule"]
    (reimb,) = by_kind["reimbursement"]
    assert reimb["amount_base"]["amount"] == "-5169.00" and reimb["dates"] == ["2026-11-30"]
    assert {"salary", "tax", "social_security", "variable_average"} <= set(by_kind)


def test_every_component_has_evidence(labs):
    for forecast in (build_forecast(**labs), build_forecast(**labs, events=[CLOSED_JUNE])):
        assert all(c["evidence"] for c in forecast["components"]), [c["id"] for c in forecast["components"]
                                                                    if not c["evidence"]]


def test_the_live_receipt_moves_the_low_by_exactly_its_amount(labs):
    before = build_forecast(**borsuk(without=("doc_rcpt412",)))
    after = build_forecast(**labs)
    moved = amount(before["min_balance"]["amount"]) - amount(after["min_balance"]["amount"])
    assert moved == Decimal("1299.00")
    assert before["inputs_hash"] != after["inputs_hash"]


def test_recurring_bank_lines_carry_a_series_id(labs):
    ids = recurring_series_ids(**{k: labs[k] for k in ("company", "accounts", "transactions", "rates", "own_ibans")})
    by_line = {t["id"]: t for t in labs["transactions"]}
    series_of = {}
    for txn_id, series_id in ids.items():
        series_of.setdefault((by_line[txn_id]["counterparty_name_raw"], series_id), 0)
    names = {name for name, _ in series_of}
    assert {"COWORKING PIOTRKOWSKA SP Z O O (SAMPLE)", "JAN KOWALSKI (SAMPLE)", "ZAKLAD UBEZPIECZEN SPOLECZNYCH",
            "CODEHARBOR INC (SAMPLE)"} <= names
    tax_series = {s for name, s in series_of if name == "URZAD SKARBOWY LODZ-POLESIE"}
    assert len(tax_series) == 3  # PIT-4, CIT-5 and VAT-7 are three series, not one average


def test_an_announced_extra_outflow_is_its_own_component(labs):
    repair = {"id": "fev_repair", "label": "Server repair", "date_from": "2026-12-02", "date_to": "2026-12-02",
              "effect": "extra_outflow", "amount": {"amount": "2000.00", "currency": "PLN"}, "source": "owner_chat"}
    base, with_repair = build_forecast(**labs), build_forecast(**labs, events=[repair])
    assert amount(with_repair["min_balance"]["amount"]) == amount(base["min_balance"]["amount"]) - 2000
    assert any(c["id"] == "c_fev_repair" and c["kind"] == "owner_event" for c in with_repair["components"])


def test_the_same_inputs_give_the_same_forecast(labs):
    assert build_forecast(**labs) == build_forecast(**labs)


def test_october_vat_comes_from_the_documents(labs):
    forecast = build_forecast(**labs)
    vat = next(c for c in forecast["components"] if c["id"] == "c_tax_vat_202610")

    assert vat["amount_base"]["amount"] == "-14300.00" and vat["dates"] == ["2026-11-25"] and vat["kind"] == "tax"
    assert "23,240.54" in vat["schedule"] and "8,940.54" in vat["schedule"]


def test_a_new_sales_invoice_raises_the_vat_and_lowers_the_low(labs):
    extra = {"id": "t_extra", "direction": "sale", "month": "2026-10", "label": "extra",
             "net": {"amount": "10000.00", "currency": "PLN"}, "vat": {"amount": "2300.00", "currency": "PLN"},
             "deductible": False}
    base = build_forecast(**labs)
    more = build_forecast(**{**labs, "tax_documents": [*labs["tax_documents"], extra]})
    vat = next(c for c in more["components"] if c["id"] == "c_tax_vat_202610")

    assert vat["amount_base"]["amount"] == "-16600.00"
    assert amount(base["min_balance"]["amount"]) - amount(more["min_balance"]["amount"]) == Decimal("2300.00")


def test_taxes_do_not_copy_the_bank_history(labs):
    forecast = build_forecast(**labs)
    taxes = [c for c in forecast["components"] if c["kind"] in ("tax", "social_security")]

    assert taxes and all(c["id"].startswith("c_tax_") for c in taxes)


def test_every_tax_component_is_one_payment_role_5_can_name(labs):
    forecast = build_forecast(**labs)
    taxes = [c for c in forecast["components"] if c["kind"] == "tax"]

    assert taxes
    for c in taxes:
        assert len(c["dates"]) == 1
        assert c["label"].split(" for ")[0].split(",")[0] in {"VAT", "CIT advance", "PIT-4"}
