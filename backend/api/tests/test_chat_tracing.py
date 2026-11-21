import json

from backend.api.tests.test_chat import ask, call, demo, with_model  # noqa: F401
from backend.api.tests.test_chat import turn as chat_turn
from backend.db.store import Store


def test_a_chat_turn_with_the_model_is_one_trace_and_the_answer_names_it(with_model, traced):
    app, _ = with_model(chat_turn(tool_calls=[call("get_forecast", {})]),
                        chat_turn(content=json.dumps({"answer": "Your lowest balance is -7,870 PLN on 5 Dec."})))
    with app:
        answer = ask(app, "When is my cash lowest?")

    assert answer["trace_id"] == "tr-test"
    assert [(name, depth) for name, depth, _ in traced.spans] == [("chat.turn", 0)]
    assert traced.tags["agent"] == "chat"
    assert traced.tags["session_id"] == answer["session_id"]
    assert traced.tags["outcome"] == "accepted"


def test_a_card_the_model_requests_in_chat_carries_the_turns_trace(with_model, db, traced):
    app, _ = with_model(chat_turn(tool_calls=[call("request_action", {"description": "Pay Nordwind 5,000 PLN"})]),
                        chat_turn(content=json.dumps({"answer": "I put the request in your inbox."})))
    with app:
        answer = ask(app, "Pay Nordwind 5,000 PLN")

    card = Store(db).get("recommendation", answer["created_recommendation_id"])
    assert card["explanation"]["generated_by"]["trace_id"] == answer["trace_id"] == "tr-test"
    assert traced.tags["created_recommendation_id"] == card["id"]


def test_a_chat_answered_without_the_model_has_no_trace(demo, db, traced):
    answer = ask(demo, "Transfer 5,000 PLN to Nordwind now")

    card = Store(db).get("recommendation", answer["created_recommendation_id"])
    assert answer["trace_id"] is None
    assert card["explanation"]["generated_by"]["trace_id"] is None
    assert traced.spans == []
