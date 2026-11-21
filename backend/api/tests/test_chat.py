"""Seam: HTTP API, POST /api/v1/chat (5.7). Without a model the chat answers from its tools deterministically;
with a model (a fake client here) the model picks the tools and its text passes the number check."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.agents import chat
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
    assert [a["id"] for a in Store(db).list("approval", company_id="co_borsuk")] == ["apr_0007"]  # the fixture's only


def test_no_execution_or_decision_tool_is_reachable_from_chat():
    names = set(chat.CHAT_TOOLS)
    assert names == {"get_cash_position", "get_forecast", "search_ledger", "explain_recommendation",
                     "add_forecast_event", "get_fx_exposure", "request_action", "run_readonly_sql",
                     "get_clients", "get_month_costs"}  # both read only
    assert not {n for n in names if "execute" in n or "decide" in n or "approve" in n}


# --- with a model --------------------------------------------------------------------------------------------------

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


# --- 5.7b: multi-turn and recovery ------------------------------------------------------------------------------------

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
