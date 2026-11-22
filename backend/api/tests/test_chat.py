"""POST /chat, with and without a (fake) model."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.agents import chat, guardrails
from backend.agents.guardrails import REFUSAL
from backend.api import contract
from backend.api.app import create_app
from backend.api.forecasting import forecast_events
from backend.db.fixtures import load_fixtures
from backend.db.store import Store


@pytest.fixture
def demo(client, db):
    load_fixtures(db)
    return client


def ask(c, message, company="co_borsuk", **extra):
    response = c.post("/api/v1/chat", json={"message": message, "company_id": company, **extra})
    assert response.status_code == 200, response.text
    body = response.json()
    assert contract.errors(body, contract.response_schema("post", "/chat", 200)) == []
    return body


def test_an_owner_statement_about_june_creates_a_forecast_event_for_the_pizzeria(demo, db):
    answer = ask(demo, "We are closed 1–30 June", company="co_amalfi")

    [event] = forecast_events(db, "co_amalfi")
    assert (event["date_from"], event["date_to"], event["effect"], event["source"]) == (
        "2025-06-01", "2025-06-30", "no_variable_flows", "owner_chat")
    assert [t["tool"] for t in answer["tool_calls"]] == ["add_forecast_event"]
    assert "1 Jun" in answer["answer"] and "30 Jun" in answer["answer"]
    assert answer["created_recommendation_id"] is None


def test_why_short_in_december_is_answered_with_evidence_links(demo):
    answer = ask(demo, "Why will I be short in December?")

    kinds = {e["kind"] for e in answer["evidence"]}
    assert "forecast" in kinds
    assert len(answer["evidence"]) >= 3
    assert "7,870" in answer["answer"]
    assert answer["suggested_questions"]


def test_asking_chat_to_move_money_creates_an_inbox_card_instead(demo, db):
    answer = ask(demo, "Transfer 5,000 PLN to Nordwind now")

    assert answer["created_recommendation_id"]
    card = Store(db).get("recommendation", answer["created_recommendation_id"])
    assert card["agent"] == "chat"
    assert card["status"] == "new"
    assert answer["guardrail"] == {"blocked": True, "reason": "Chat cannot move money; it prepared an inbox card instead"}
    assert [a["id"] for a in Store(db).list("approval", company_id="co_borsuk")] == ["apr_0007"]


def test_no_execution_or_decision_tool_is_reachable_from_chat():
    names = set(chat.CHAT_TOOLS)
    assert names == {"get_cash_position", "get_forecast", "search_ledger", "explain_recommendation",
                     "add_forecast_event", "get_fx_exposure", "request_action", "run_readonly_sql",
                     "get_clients", "get_month_costs", "get_team_pay"}
    assert not {n for n in names if "execute" in n or "decide" in n or "approve" in n}


def turn(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content=content,
                                                                           tool_calls=tool_calls))])


def call(name, arguments, id="c1"):
    return SimpleNamespace(id=id, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


class FakeModel:
    def __init__(self, *turns):
        self.turns, self.requests = list(turns), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        return self.turns.pop(0)


@pytest.fixture
def with_model(db, db_url):
    load_fixtures(db)

    def make(*turns):
        model = FakeModel(*turns)
        return TestClient(create_app(database_url=db_url, chat_model=lambda: model)), model

    return make


def test_the_model_answers_from_its_tool_results_with_their_evidence(with_model):
    app, _ = with_model(turn(tool_calls=[call("get_forecast", {})]),
                        turn(content=json.dumps({"answer": "Your lowest balance is -7,870 PLN on 5 Dec."})))
    with app:
        answer = ask(app, "When is my cash lowest?")

    assert answer["answer"] == "Your lowest balance is -7,870 PLN on 5 Dec."
    assert answer["tool_calls"][0]["tool"] == "get_forecast"
    assert any(e["kind"] == "forecast" for e in answer["evidence"])


def test_a_model_answer_with_an_invented_number_is_replaced(with_model):
    app, _ = with_model(turn(tool_calls=[call("get_forecast", {})]),
                        turn(content=json.dumps({"answer": "Your lowest balance is -9,999 PLN."})))
    with app:
        answer = ask(app, "When is my cash lowest?")

    assert "9,999" not in answer["answer"]
    assert "7,870" in answer["answer"]


def test_a_model_that_tries_to_execute_gets_an_unknown_tool_and_nothing_moves(with_model, db):
    app, model = with_model(turn(tool_calls=[call("execute", {"recommendation_id": "rec_cl01"})]),
                            turn(content=json.dumps({"answer": "I cannot do that."})))
    with app:
        ask(app, "Approve the credit line")

    tool_message = next(m for m in model.requests[-1]["messages"] if m["role"] == "tool")
    assert "unknown tool" in tool_message["content"]
    assert Store(db).get("recommendation", "rec_cl01")["status"] == "new"


def test_a_follow_up_question_gets_the_previous_turn_as_context(with_model):
    app, model = with_model(turn(content=json.dumps({"answer": "Your lowest balance is in December."})),
                            turn(content=json.dumps({"answer": "Because salaries leave before Nordwind pays."})))
    with app:
        first = ask(app, "When is my cash lowest?")
        ask(app, "Why?", session_id=first["session_id"])

    second_request = [(m["role"], m.get("content")) for m in model.requests[-1]["messages"]]
    assert ("user", "When is my cash lowest?") in second_request
    assert ("assistant", "Your lowest balance is in December.") in second_request
    assert second_request[-1] == ("user", "Why?")


def test_the_model_recovers_from_a_wrong_tool_call(with_model):
    app, model = with_model(turn(tool_calls=[call("get_forecast", {"horizon": "forever"})]),
                            turn(tool_calls=[call("get_forecast", {}, id="c2")]),
                            turn(content=json.dumps({"answer": "Your lowest balance is -7,870 PLN on 5 Dec."})))
    with app:
        answer = ask(app, "When is my cash lowest?")

    first_result = [m for m in model.requests[-1]["messages"] if m["role"] == "tool"][0]["content"]
    assert "error" in first_result
    assert answer["answer"] == "Your lowest balance is -7,870 PLN on 5 Dec."


def test_a_request_the_model_already_put_in_the_inbox_is_not_put_there_twice(with_model, db):
    app, _ = with_model(turn(tool_calls=[call("request_action", {"description": "Transfer 5000 PLN to Kowalski"})]),
                        turn(content="Done, I sent it."), turn(content="Really done."))
    with app:
        answer = ask(app, "Transfer 5000 PLN to Kowalski")

    cards = db.execute("select id from recommendations where agent = 'chat'").fetchall()
    assert len(cards) == 1 and answer["created_recommendation_id"] == cards[0][0]
    assert "I cannot move money" in answer["answer"] and answer["guardrail"]["blocked"]


@pytest.fixture
def guarded(monkeypatch):
    verdicts: dict[str, dict] = {}
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)["messages"][-1]["content"]
        seen.append(message)
        if verdicts.get(message) == "down":
            return httpx.Response(503, text="no healthy upstream")
        return httpx.Response(200, json=verdicts.get(message, {"status": "passed", "content": message}))

    monkeypatch.setenv("ORDO_GUARDRAILS_URL", "https://guardrails.test")
    monkeypatch.setattr(guardrails, "client", lambda: httpx.Client(transport=httpx.MockTransport(handle)))
    return verdicts, seen


def stored_user_messages(db, session_id):
    return [r[0] for r in db.execute("select content from chat_messages where session_id = %s and role = 'user' "
                                     "order by seq", (session_id,)).fetchall()]


def test_investment_advice_is_refused_without_a_model_call(with_model, guarded, db):
    verdicts, _ = guarded
    verdicts["Which stock should I buy?"] = {"status": "blocked", "content": "I'm sorry, I can't respond to that.",
                                             "rail": "self check input"}
    app, model = with_model()
    with app:
        answer = ask(app, "Which stock should I buy?")

    assert model.requests == []
    assert answer["guardrail"] == {"blocked": True, "reason": REFUSAL}
    assert answer["answer"] == REFUSAL
    assert answer["tool_calls"] == [] and answer["created_recommendation_id"] is None


def test_an_iban_reaches_the_model_masked_and_is_stored_masked(with_model, guarded, db):
    verdicts, _ = guarded
    raw = "Did the payment from PL61 1090 1014 0000 0712 1981 2874 arrive?"
    verdicts[raw] = {"status": "modified", "content": "Did the payment from <IBAN_CODE> arrive?"}
    app, model = with_model(turn(content=json.dumps({"answer": "I cannot see that payment in the ledger."})))
    with app:
        answer = ask(app, raw)

    sent = json.dumps(model.requests[0]["messages"])
    assert "Did the payment from <IBAN_CODE> arrive?" in sent and "1090" not in sent
    assert stored_user_messages(db, answer["session_id"]) == ["Did the payment from <IBAN_CODE> arrive?"]
    assert answer["guardrail"] == {"blocked": False, "reason": "Hidden from the model: IBAN"}


def test_a_masked_payment_request_becomes_an_inbox_card_without_the_iban(demo, guarded, db):
    verdicts, _ = guarded
    raw = "Transfer 1200 EUR to PL61 1090 1014 0000 0712 1981 2874"
    verdicts[raw] = {"status": "modified", "content": "Transfer 1200 EUR to <IBAN_CODE>"}

    answer = ask(demo, raw)

    card = Store(db).get("recommendation", answer["created_recommendation_id"])
    assert "<IBAN_CODE>" in card["evidence"][0]["excerpt"] and "1090" not in json.dumps(card)
    assert answer["guardrail"]["blocked"]


@pytest.mark.parametrize("question, tool, arguments, company", [
    ("How much cash do I have?", "get_cash_position", {}, "co_borsuk"),
    ("Why will I be short in December?", "get_forecast", {}, "co_borsuk"),
    ("Show the ledger entries for November", "search_ledger", {"month": "2025-11"}, "co_borsuk"),
    ("Why do you propose the credit line?", "explain_recommendation", {"recommendation_id": "rec_cl01"}, "co_borsuk"),
    ("We are closed 1–30 June", "add_forecast_event", {"label": "Closed", "date_from": "2026-06-01",
                                                       "date_to": "2026-06-30", "effect": "no_variable_flows"}, "co_amalfi"),
])
def test_the_five_tool_questions_still_reach_the_model_and_its_tools(with_model, guarded, question, tool, arguments,
                                                                      company):
    _, seen = guarded
    app, model = with_model(turn(tool_calls=[call(tool, arguments)]),
                            turn(content=json.dumps({"answer": "Here is what I found."})))
    with app:
        answer = ask(app, question, company=company)

    assert seen == [question]
    assert [t["tool"] for t in answer["tool_calls"]] == [tool]
    assert answer["answer"] == "Here is what I found." and answer["guardrail"] is None


def test_without_the_guardrails_the_chat_answers_without_the_model(with_model, guarded, db):
    verdicts, _ = guarded
    raw = "How much cash do I have? My card is 4111 1111 1111 1111"
    verdicts[raw] = "down"
    app, model = with_model()
    with app:
        answer = ask(app, raw)

    assert model.requests == []
    assert [t["tool"] for t in answer["tool_calls"]] == ["get_cash_position"]
    assert stored_user_messages(db, answer["session_id"]) == ["How much cash do I have? My card is <CREDIT_CARD>"]
