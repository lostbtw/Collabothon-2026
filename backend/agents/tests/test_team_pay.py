"""The chat's pay tool on the Borsuk Labs bank history: the owner's own pay is company finance, answered from the engine."""
import json
from types import SimpleNamespace

import pytest

from backend.agents import chat
from backend.db.seed import seed
from backend.db.store import Store
from backend.finance.tests.data import borsuk

OWNER_PAY = {"amount": "7000.00", "currency": "PLN"}


@pytest.fixture
def labs(db):
    seed(db)
    s = Store(db)
    data = borsuk()
    for acc in data["accounts"]:
        s.put("account", {**acc, "company_id": "co_borsuk", "kind": "company_bank", "name": acc["id"]},
              company_id="co_borsuk")
    for t in data["transactions"]:
        s.add("transaction", t, company_id="co_borsuk")
    db.commit()
    return db


def test_in_two_months_is_january_with_the_owners_board_fee_on_the_last_business_day(labs):
    result = chat.get_team_pay(labs, "co_borsuk", months_ahead=2)

    assert (result["as_of_date"], result["month"]) == ("2026-11-21", "2027-01")
    you = next(p for p in result["people"] if p["is_the_owner"])
    assert you["name"] == "Tomasz Borsuk"
    assert you["expected_in_month"] == [{"date": "2027-01-29", "amount": OWNER_PAY}]
    assert [p["amount"] for p in you["last_payments"]] == [OWNER_PAY] * 3
    assert you["paid_in_month"] == {"amount": "0.00", "currency": "PLN"}


def test_a_past_month_shows_what_was_paid_and_nothing_expected(labs):
    result = chat.get_team_pay(labs, "co_borsuk", month="2026-10")

    you = next(p for p in result["people"] if p["is_the_owner"])
    assert you["paid_in_month"] == OWNER_PAY
    assert you["expected_in_month"] == []
    assert result["forecast_runs_until"] is None


def test_without_the_model_the_salary_question_gets_the_owners_pay(labs):
    answer, evidence, trace, created, guardrail = chat.deterministic(labs, "co_borsuk", "What salary will I get in two months?")

    assert answer.startswith("In January 2027 you can expect 7,000.00 PLN on 29 Jan.")
    assert trace == [{"tool": "get_team_pay", "arguments": {"months_ahead": 2}, "duration_ms": 0}]
    assert evidence and created is None and guardrail is None


def turn(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content=content,
                                                                           tool_calls=tool_calls))])


def test_the_model_knows_today_and_its_pay_answer_passes_the_number_check(labs):
    requests = []
    turns = [turn(tool_calls=[SimpleNamespace(id="c1", type="function", function=SimpleNamespace(
                 name="get_team_pay", arguments=json.dumps({"months_ahead": 2})))]),
             turn(json.dumps({"answer": "On 29 January 2027 you should get 7,000.00 PLN, like the last months."}))]

    def create(**request):
        requests.append(request)
        return turns.pop(0)

    model = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    reply = chat.answer(labs, "co_borsuk", "What salary will I get in two months?", None, model)

    assert reply["answer"] == "On 29 January 2027 you should get 7,000.00 PLN, like the last months."
    assert [t["tool"] for t in reply["tool_calls"]] == ["get_team_pay"]
    system = requests[0]["messages"][0]["content"]
    assert "Today is 2026-11-21." in system and "get_team_pay" in system
    assert "get_team_pay" in {t["function"]["name"] for t in requests[0]["tools"]}
