"""FX Shield with a scripted model: pins what the agent does with an answer, not which answer is right."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.agents import fx
from backend.agents.chat import get_fx_exposure
from backend.agents.main import HANDLERS
from backend.api import contract
from backend.api.app import create_app
from backend.db.store import Store
from backend.finance import engine
from backend.finance.tests.test_engine import labs_db  # noqa: F401  (fixture: Borsuk Labs in the database)

LAKESHORE, NORDWIND = "doc_fv_2026_11_045", "doc_fv_2026_10_044"
HEDGE_WHY = "A loss of 6,594.83 PLN is a large part of a weak month for your company, so fixing the rate is worth it."
INFORM_WHY = "A loss of 994.46 PLN is small for your company, even with your cash forecast below zero."
IGNORE_WHY = "This bill is far too small to matter for your company."


def updated():
    return {"id": "evt_fx", "type": "forecast.updated", "occurred_at": "2026-11-21T10:15:03Z",
            "company_id": "co_borsuk", "payload": {"forecast_id": None}}


def fx_cards(db, *statuses):
    return [r for r in Store(db).list("recommendation", company_id="co_borsuk", agent="fx")
            if not statuses or r["status"] in statuses]


def open_by_invoice(db):
    return {r["subject"]["id"]: r for r in fx_cards(db, "new", "seen")}


def turn(content=None, tool_calls=None):
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if tool_calls else "stop")])


class FakeModel:
    def __init__(self, *turns, error=None):
        self.turns, self.error, self.requests = list(turns), error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.turns.pop(0) if self.turns else turn(content="{}")


def answer(action, reference, reason):
    return turn(content=json.dumps({"action": action, "reference": reference, "reason": reason}))


def only(document_id, monkeypatch, change=lambda a: a):
    real = engine.fx_assessments
    monkeypatch.setattr(engine, "fx_assessments", lambda conn, company_id: [
        change(a) for a in real(conn, company_id) if a["document_id"] == document_id])


def test_the_agent_listens_to_forecast_updated():
    assert fx.on_forecast_updated in HANDLERS["forecast.updated"]


def test_hedge_gives_a_simulated_forward_to_approve_compared_with_the_reference_the_model_chose(labs_db, monkeypatch):  # noqa: F811
    only(LAKESHORE, monkeypatch)
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("hedge", "money_in_weakest_month", HEDGE_WHY)))
    card = open_by_invoice(labs_db)[LAKESHORE]
    assert (card["type"], card["control_level"], card["execution_mode"], card["severity"]) == \
        ("fx_hedge", "approval_required", "simulated", "warning")
    assert card["proposed_action"]["params"] == {
        "sell_currency": "USD", "buy_currency": "PLN", "notional": {"amount": "40000.00", "currency": "USD"},
        "rate": "4.0491", "value_date": "2027-01-05", "hedge_ratio": 1.0, "bank": "Commerzbank"}
    assert card["proposed_action"]["preview"].startswith(
        "SIMULATED: books a forward to sell 40,000 USD for 161,964.64 PLN on 5 Jan")
    assert "6,594.83 PLN, 11.0% of money in during your weakest of the last 10 months (60,147 PLN)" in card["summary"]
    assert card["explanation"]["why"][0] == HEDGE_WHY
    assert "profit" not in json.dumps(card).lower()
    assert any("illustrative, not an offer" in a for a in card["explanation"]["assumptions"])
    assert {e["kind"] for e in card["evidence"]} == {"document", "fx_rate", "rule"}
    assert contract.entity_errors("recommendation", card) == []


def test_another_reference_changes_only_what_the_loss_is_compared_with(labs_db, monkeypatch):  # noqa: F811
    only(LAKESHORE, monkeypatch)
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("hedge", "cash_today", HEDGE_WHY)))
    card = open_by_invoice(labs_db)[LAKESHORE]
    assert "6,594.83 PLN, 17.2% of the cash you hold today (38,401.15 PLN)" in card["summary"]


def test_inform_gives_an_info_card_with_the_numbers(labs_db, monkeypatch):  # noqa: F811
    only(NORDWIND, monkeypatch)
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("inform", "money_in_median_month", INFORM_WHY)))
    card = open_by_invoice(labs_db)[NORDWIND]
    assert (card["type"], card["control_level"], card["execution_mode"], card["proposed_action"]) == \
        ("info", "recommendation", "none", None)
    assert all(t in card["summary"] for t in ("994.46 PLN", "0.9%", "16 days", "further below zero"))
    assert card["explanation"]["why"][0] == INFORM_WHY
    assert contract.entity_errors("recommendation", card) == []


def test_ignore_leaves_the_inbox_empty_and_keeps_a_closed_record(labs_db, monkeypatch):  # noqa: F811
    only(NORDWIND, monkeypatch)
    model = FakeModel(answer("ignore", "money_in_median_month", IGNORE_WHY))
    assert len(fx.on_forecast_updated(labs_db, updated(), model=model)) == 1
    assert open_by_invoice(labs_db) == {}
    (record,) = fx_cards(labs_db)
    assert (record["status"], record["type"], record["explanation"]["why"]) == ("expired", "info", [IGNORE_WHY])
    assert contract.entity_errors("recommendation", record) == []
    assert fx.on_forecast_updated(labs_db, updated(), model=model) == [] and len(model.requests) == 1


def test_the_model_is_given_the_company_facts_and_told_how_to_judge(labs_db, monkeypatch):  # noqa: F811
    only(NORDWIND, monkeypatch)
    model = FakeModel(answer("inform", "money_in_median_month", INFORM_WHY))
    fx.on_forecast_updated(labs_db, updated(), model=model)
    system, user = (m["content"] for m in model.requests[0]["messages"][:2])
    assert all(t in system for t in ("no profit on a single invoice", "no fixed threshold", "varies",
                                     "undesirable but not critical", "never as a reason on its own", "reference"))
    for t in ('"months"', '"loss_vs_references"', '"money_in_weakest_month"', '"bad_case_takes_balance_below_zero": true'):
        assert t in user
    assert "profit" not in user


def test_an_answer_that_breaks_the_rules_gives_no_card_and_is_asked_again_next_time(labs_db, monkeypatch):  # noqa: F811
    only(NORDWIND, monkeypatch)
    bad = [answer("inform", "money_in_median_month", "You could lose 9,999 PLN on this order, which is fine for you."),
           answer("inform", "an_amount_the_model_made_up", INFORM_WHY),
           turn(content="not json at all")]
    for a in bad:
        assert fx.on_forecast_updated(labs_db, updated(), model=FakeModel(a)) == []
    assert fx_cards(labs_db) == []
    assert len(fx.on_forecast_updated(labs_db, updated(),
                                      model=FakeModel(answer("inform", "money_in_median_month", INFORM_WHY)))) == 1


def test_no_model_or_a_model_error_decides_nothing(labs_db):  # noqa: F811
    assert fx.on_forecast_updated(labs_db, updated(), model=None) == []
    assert fx.on_forecast_updated(labs_db, updated(), model=FakeModel(error=RuntimeError("model down"))) == []
    assert fx_cards(labs_db) == []


def test_the_model_is_asked_once_per_set_of_numbers_and_new_numbers_replace_the_card(labs_db, monkeypatch):  # noqa: F811
    only(LAKESHORE, monkeypatch)
    model = FakeModel(answer("inform", "money_in_median_month", HEDGE_WHY.replace("so fixing", "but fixing")),
                      answer("hedge", "money_in_weakest_month", HEDGE_WHY))
    assert len(fx.on_forecast_updated(labs_db, updated(), model=model)) == 1
    assert fx.on_forecast_updated(labs_db, updated(), model=model) == [] and len(model.requests) == 1
    monkeypatch.undo()
    only(LAKESHORE, monkeypatch, lambda a: {**a, "spot": "4.1000"})
    assert len(fx.on_forecast_updated(labs_db, updated(), model=model)) == 1
    assert sorted((r["type"], r["status"]) for r in fx_cards(labs_db)) == [("fx_hedge", "new"), ("info", "superseded")]


def test_an_approved_hedge_is_not_asked_again(labs_db, monkeypatch):  # noqa: F811
    only(LAKESHORE, monkeypatch)
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("hedge", "money_in_weakest_month", HEDGE_WHY)))
    card = open_by_invoice(labs_db)[LAKESHORE]
    Store(labs_db).put("recommendation", {**card, "status": "approved"})
    monkeypatch.undo()
    only(LAKESHORE, monkeypatch, lambda a: {**a, "spot": "4.1000"})
    model = FakeModel()
    assert fx.on_forecast_updated(labs_db, updated(), model=model) == [] and model.requests == []


def test_a_covered_invoice_can_only_be_informed_about(labs_db, monkeypatch):  # noqa: F811
    only(NORDWIND, monkeypatch, lambda a: {**a, "status": "naturally_hedged", "loss_vs_references": []})
    why = "The euro you receive and pay at about the same time already cancel each other out."
    assert fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("hedge", "none", why))) == []
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("inform", "none", why)))
    card = open_by_invoice(labs_db)[NORDWIND]
    assert (card["type"], card["title"].endswith("is already covered in EUR")) == ("info", True)
    assert contract.entity_errors("recommendation", card) == []


def test_the_api_and_the_chat_show_the_engines_exposure_and_the_card_the_owner_sees(labs_db, db_url):  # noqa: F811
    fx.on_forecast_updated(labs_db, updated(), model=FakeModel(answer("hedge", "money_in_weakest_month", HEDGE_WHY),
                                                               answer("inform", "money_in_median_month", INFORM_WHY)))
    labs_db.commit()
    with TestClient(create_app(database_url=db_url)) as client:
        body = client.get("/api/v1/fx/exposure", params={"company_id": "co_borsuk"}).json()
    assert contract.errors(body, contract.response_schema("get", "/fx/exposure", 200)) == []
    items = {i["document_id"]: i for i in body["items"]}
    verdicts = {items[d].get("verdict") for d in (LAKESHORE, NORDWIND)}
    assert verdicts == {"hedge_proposed", "not_worth_it"}
    assert all(items[d]["recommendation_id"].startswith("rec_fx_") for d in (LAKESHORE, NORDWIND))
    assert {i["document_id"] for i in get_fx_exposure(labs_db, "co_borsuk")["items"]} == {LAKESHORE, NORDWIND}


def test_an_invoice_with_an_executed_forward_is_not_sent_to_the_model(labs_db):  # noqa: F811
    from backend.finance.tests.test_fx import book_forward
    book_forward(labs_db)
    model = FakeModel(answer("inform", "money_in_median_month", INFORM_WHY))
    fx.on_forecast_updated(labs_db, updated(), model=model)
    assert len(model.requests) == 1 and LAKESHORE not in model.requests[0]["messages"][1]["content"].split(".")[0]
