"""Seam: database -> recompute -> stored Forecast + forecast.updated (#28). Needs the test database."""
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.db.contracts import Forecast
from backend.db.events import events_after, new_event
from backend.db.seed import seed
from backend.db.store import Store
from backend.finance import engine
from backend.finance.handlers import DIRTY, on_inputs_changed, recompute_due
from backend.pipeline.normalise.bank import transaction_id

from .data import CLOSED_JUNE, PIZZERIA_CSV, SCENARIO, bank_lines, borsuk, pizzeria, scenario_documents

SALES = [  # the story's open sales invoices on 21 Nov (role 4 scenario)
    ("doc_fv_2026_10_042", "2026/10/042", "Meblostyl sp. z o.o. (SAMPLE)", None, "36900.00", "PLN", "2026-10-31",
     "2026-11-27"),
    ("doc_fv_2026_10_044", "2026/10/044", "Nordwind Logistik GmbH (SAMPLE)", "cp_nordwind", "18400.00", "EUR",
     "2026-10-15", "2026-11-14"),
    ("doc_fv_2026_11_045", "2026/11/045", "Lakeshore Robotics Inc. (SAMPLE)", None, "40000.00", "USD", "2026-11-20",
     "2027-01-05"),
]


def events(db, type):
    return [e for _, e in events_after(db, 0, limit=5000) if e["type"] == type]


@pytest.fixture
def labs_db(db):
    """Borsuk Labs in the database: bank lines, open sales invoices, Nordwind's delay, 10 approved debts."""
    seed(db)
    for p in json.loads((SCENARIO / "people.json").read_text(encoding="utf-8")):  # the full team (role 4 scenario)
        db.execute("insert into people (id, company_id, name, email, role) values (%s, %s, %s, %s, %s) "
                   "on conflict do nothing", (p["id"], p["company_id"], p["name"], p["email"], p["role"]))
    db.commit()
    s = Store(db)
    data = borsuk()
    for acc in data["accounts"]:
        s.put("account", {**acc, "company_id": "co_borsuk", "kind": "company_bank", "name": acc["id"]},
              company_id="co_borsuk")
    for t in data["transactions"]:
        s.add("transaction", t, company_id="co_borsuk")
    s.put("counterparty", {"id": "cp_nordwind", "company_id": "co_borsuk", "name": "Nordwind Logistik GmbH (SAMPLE)",
                           "kind": "customer", "typical_payment_delay_days": 23}, company_id="co_borsuk")
    scenario = {d["number"]: d for d in scenario_documents()}
    story = {"2026/10/041", "2026/10/042", "2026/10/043", "2026/10/044"}  # stored below with their story ids

    def totals(number, gross, ccy):  # net and VAT from the scenario's invoice; Lakeshore 2026/11/045 has none
        t = {"gross": {"amount": gross, "currency": ccy}}
        if number in scenario:
            t |= {"net": scenario[number]["totals"]["net"], "vat": scenario[number]["totals"]["vat"]}
        return t

    for id_, number, buyer, cp, gross, ccy, issued, due in SALES:
        s.put("document", {"id": id_, "company_id": "co_borsuk", "direction": "sale", "status": "approved",
                           "number": number, "issue_date": issued, "due_date": due,
                           "buyer": {"name": buyer, "counterparty_id": cp},
                           "totals": totals(number, gross, ccy)}, company_id="co_borsuk")
    paid = [("doc_fv_2026_10_041", "Piekarnia Złoty Kłos sp. z o.o. (SAMPLE)", "8610.00", "2026-11-04", "FV 2026/10/041"),
            ("doc_fv_2026_10_043", "Kadrownia sp. z o.o. (SAMPLE)", "4920.00", "2026-11-15", "ZAPLATA ZA FV 2026/10/043")]
    for id_, buyer, gross, due, reference in paid:  # October invoices already paid in November (matched)
        line = next(t for t in data["transactions"] if t["description"] == reference)
        s.put("document", {"id": id_, "company_id": "co_borsuk", "direction": "sale", "status": "approved",
                           "number": id_[7:].replace("_", "/"), "issue_date": "2026-10-31", "due_date": due,
                           "buyer": {"name": buyer, "counterparty_id": None},
                           "totals": totals(id_[7:].replace("_", "/"), gross, "PLN")}, company_id="co_borsuk")
        s.put("match", {"id": f"mat_{id_}", "match_type": "sales_invoice_payment", "document_id": id_,
                        "transaction_id": line["id"], "status": "confirmed"}, company_id="co_borsuk")
    transaction_ids = {t["id"] for t in data["transactions"]}
    for doc in scenario_documents():  # the rest of the books: history is paid and matched, none of it is open
        if doc["number"] in story:
            continue
        doc = dict(doc)
        line = doc.get("bank_line")
        if doc["direction"] == "sale" and line:
            doc.pop("due_date")
            txn = transaction_id(line["account"], line["entry_reference"])
            assert txn in transaction_ids
            s.put("match", {"id": f"mat_{doc['id']}", "match_type": "sales_invoice_payment", "document_id": doc["id"],
                            "transaction_id": txn, "status": "confirmed"}, company_id="co_borsuk")
        s.put("document", doc, company_id="co_borsuk")
    for e in data["ledger_entries"]:
        s.put("ledger_entry", {**e, "company_id": "co_borsuk", "date": "2026-11-20", "category": "reimbursements",
                               "amount": e["amount_base"], "paid_by": "not_applicable", "approval_id": "apr_t",
                               "created_by": "test", "evidence": []}, company_id="co_borsuk")
    return db


def test_recompute_stores_the_forecast_and_emits_forecast_updated(labs_db):
    forecast = engine.recompute(labs_db, "co_borsuk")

    Forecast.model_validate(forecast)
    assert forecast["opening_balance"]["amount"] == "38401.15"
    assert forecast["first_negative_date"] == "2026-11-30"
    assert forecast["min_balance"]["amount"]["amount"] == "-13178.34"
    nordwind = next(c for c in forecast["components"] if "Nordwind" in c["label"] and c["kind"] == "known_receivable")
    assert nordwind["dates"] == ["2026-12-07"] and nordwind["amount_base"]["amount"] == "81144.00"
    assert engine.latest_base(labs_db, "co_borsuk")["id"] == forecast["id"]
    (updated,) = events(labs_db, "forecast.updated")
    assert updated["payload"] == {"forecast_id": forecast["id"], "min_balance": forecast["min_balance"]["amount"],
                                  "min_balance_previous": None, "first_negative_date": "2026-11-30"}


def test_unchanged_inputs_do_nothing(labs_db):
    first = engine.recompute(labs_db, "co_borsuk")
    again = engine.recompute(labs_db, "co_borsuk")
    assert again["id"] == first["id"]
    assert len(events(labs_db, "forecast.updated")) == 1


def test_recurring_bank_lines_get_their_series_id(labs_db):
    engine.recompute(labs_db, "co_borsuk")
    lines = Store(labs_db).list("transaction", company_id="co_borsuk")
    tagged = [t for t in lines if t.get("recurring_series_id")]
    assert len(tagged) > 200
    tax = {t["recurring_series_id"] for t in tagged if t["counterparty_name_raw"] == "URZAD SKARBOWY LODZ-POLESIE"}
    assert len(tax) == 3


def test_a_new_debt_to_the_team_gives_a_new_forecast_with_the_previous_low(labs_db):
    first = engine.recompute(labs_db, "co_borsuk")
    Store(labs_db).put("ledger_entry", {"id": "led_new", "company_id": "co_borsuk", "type": "reimbursement_liability",
                                        "status": "approved", "cash_date": "2026-11-30", "date": "2026-11-21",
                                        "amount_base": {"amount": "-500.00", "currency": "PLN"},
                                        "amount": {"amount": "-500.00", "currency": "PLN"}, "explanation": "test"},
                       company_id="co_borsuk")
    second = engine.recompute(labs_db, "co_borsuk")

    assert Decimal(second["min_balance"]["amount"]["amount"]) == Decimal(first["min_balance"]["amount"]["amount"]) - 500
    latest = events(labs_db, "forecast.updated")[-1]["payload"]
    assert latest["min_balance_previous"] == first["min_balance"]["amount"]


def test_input_events_are_debounced_per_company(labs_db):
    DIRTY.clear()
    event = new_event("transaction.ingested", "co_borsuk", {"transaction_id": "x"}, producer="test")
    on_inputs_changed(labs_db, event)
    seen = DIRTY["co_borsuk"][0]

    assert recompute_due(labs_db, now=seen + 1.0) == []          # within 2 s: wait for more events
    assert recompute_due(labs_db, now=seen + 2.0) == ["co_borsuk"]
    assert events(labs_db, "forecast.updated")[-1]["causation_id"] == event["id"]
    assert DIRTY == {}


def test_role_5_api_recomputes_with_the_engine_and_takes_owner_events(labs_db, db_url):
    with TestClient(create_app(database_url=db_url)) as client:
        forecast = client.post("/api/v1/forecast/recompute", params={"company_id": "co_borsuk"}).json()
        assert forecast["min_balance"]["amount"]["amount"] == "-13178.34"
        repair = {"label": "Server repair", "date_from": "2026-12-02", "date_to": "2026-12-02",
                  "effect": "extra_outflow", "amount": {"amount": "2000.00", "currency": "PLN"}}
        after = client.post("/api/v1/forecast/events", json=repair, params={"company_id": "co_borsuk"}).json()
        assert after["min_balance"]["amount"]["amount"] == "-15178.34"
        assert client.get("/api/v1/forecast/latest", params={"company_id": "co_borsuk"}).json()["id"] == after["id"]


def test_a_credit_line_scenario_closes_the_gap_on_the_base_forecast(labs_db):
    base = engine.recompute(labs_db, "co_borsuk")
    what_if = engine.scenario(labs_db, "co_borsuk",
                              {"credit_line": {"limit": {"amount": "30000.00", "currency": "PLN"}, "from": "2026-11-28"}})

    assert what_if["scenario_of"] == base["id"]
    assert what_if["first_negative_date"] is None
    assert not any(a["type"] == "cash_gap" for a in what_if["alerts"])
    low = min(Decimal(p["balance"]) + (30000 if p["date"] >= "2026-11-28" else 0) for p in base["points"])
    assert Decimal(what_if["min_balance"]["amount"]["amount"]) == low
    assert any(c["kind"] == "scenario_action" for c in what_if["components"])
    assert engine.latest_base(labs_db, "co_borsuk")["id"] == base["id"]  # a scenario is never the base
    Forecast.model_validate(what_if)


@pytest.mark.skipif(PIZZERIA_CSV is None, reason="pizzeria CSV not present (git-ignored event material)")
def test_the_pizzeria_from_the_database_with_the_june_closure(db):
    seed(db)
    s = Store(db)
    account = {"id": "acc_pizzeria", "company_id": "co_amalfi", "kind": "company_bank", "currency": "EUR",
               "include_in_liquidity": True, "opening_balance": {"amount": "0.00", "currency": "EUR"},
               "balance": {"amount": "33266.35", "currency": "EUR"}, "balance_at": "2025-12-31T23:59:59Z"}
    s.put("account", account, company_id="co_amalfi")
    for t in bank_lines(PIZZERIA_CSV, account):
        s.add("transaction", t, company_id="co_amalfi")
    db.execute("insert into forecast_events (id, company_id, doc) values (%s, %s, %s::jsonb)",
               (CLOSED_JUNE["id"], "co_amalfi", json.dumps(CLOSED_JUNE)))
    db.commit()

    forecast = engine.recompute(db, "co_amalfi")

    assert forecast["opening_balance"]["amount"] == "1691.15"   # back from the bank's year-end balance
    assert forecast["min_balance"]["date"] == "2025-07-03"
    assert forecast["min_balance"]["amount"]["amount"] == pizzeria_expected()


def pizzeria_expected() -> str:
    from backend.finance.forecast import build_forecast
    return build_forecast(**pizzeria(), events=[CLOSED_JUNE], horizon_days=60)["min_balance"]["amount"]["amount"]


def test_an_invoice_whose_payment_is_in_the_bank_is_not_expected_again(labs_db):
    """Role 3 leaves most matches `suggested` until the owner confirms them; the money has moved all the same.
    Found with the full scenario: every sales invoice of the year was expected as a future receipt (1.27 m PLN)."""
    s = Store(labs_db)
    june = next(t for t in s.list("transaction", company_id="co_borsuk") if t["description"] == "FV 2026/10/041")
    s.put("document", {"id": "doc_paid_june", "company_id": "co_borsuk", "direction": "sale", "status": "extracted",
                       "number": "2026/06/042", "issue_date": "2026-06-30", "due_date": "2026-07-14",
                       "buyer": {"name": "Meblostyl sp. z o.o. (SAMPLE)", "counterparty_id": None},
                       "totals": {"gross": {"amount": "36408.00", "currency": "PLN"}}}, company_id="co_borsuk")

    def expected():
        company = engine._company(labs_db, "co_borsuk")
        items, _ = engine._open_items(s, company, company["as_of_date"])
        return {i["id"] for i in items}

    assert "doc_paid_june" in expected()  # no match yet: open
    s.put("match", {"id": "mat_paid_june", "match_type": "sales_invoice_payment", "document_id": "doc_paid_june",
                    "transaction_id": june["id"], "status": "suggested"}, company_id="co_borsuk")
    assert "doc_paid_june" not in expected()  # suggested, not confirmed: paid all the same
    s.put("match", {"id": "mat_paid_june", "match_type": "sales_invoice_payment", "document_id": "doc_paid_june",
                    "transaction_id": june["id"], "status": "rejected"}, company_id="co_borsuk")
    assert "doc_paid_june" in expected()  # the owner said no: open again
