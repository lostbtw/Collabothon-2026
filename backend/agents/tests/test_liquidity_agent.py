"""Seam: the liquidity agent on forecast.updated, with a fake model client at the LLM boundary."""
import copy
import json
from types import SimpleNamespace

import pytest

from backend.agents.liquidity import on_forecast_updated
from backend.api import contract
from backend.db.fixtures import read
from backend.db.seed import seed
from backend.db.store import Store


def forecast_fixture():
    return copy.deepcopy(read("forecast")[0])


def updated(forecast_id):
    return {"id": f"evt_{forecast_id}", "type": "forecast.updated", "occurred_at": "2026-11-21T10:15:03Z",
            "company_id": "co_borsuk", "payload": {"forecast_id": forecast_id}}


@pytest.fixture
def world(db):
    seed(db)
    s = Store(db)
    s.add("forecast", forecast_fixture())
    for counterparty in read("counterparty"):
        s.add("counterparty", counterparty)
    return s


def cards(s):
    return [r for r in s.list("recommendation", company_id="co_borsuk") if r["agent"] == "liquidity"]



def tool_call(name, arguments, id="call_1"):
    return SimpleNamespace(id=id, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


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


def final(title, summary, why):
    return turn(content=json.dumps({"title": title, "summary": summary, "why": why}))



def test_borsuk_alert_without_a_model_gives_the_template_credit_line_card(db, world):
    on_forecast_updated(db, updated("fc_20261121a"), model=None)

    [card] = cards(world)
    assert card["title"] == "Open a 30,000 PLN credit line before 30 November"
    assert (card["type"], card["control_level"], card["execution_mode"]) == ("credit_line", "approval_required", "simulated")
    assert card["severity"] == "critical"
    assert len(card["explanation"]["why"]) == 3
    calculation = {row["label"]: row["value"] for row in card["explanation"]["calculation"]}
    assert calculation["Lowest projected balance"] == "-7,870 PLN on 5 Dec"
    assert calculation["Stress case (Nordwind pays 21 Dec)"] == "-28,170 PLN on 21 Dec"
    assert calculation["Proposed limit"] == "30,000 PLN"
    alternatives = [a["label"] for a in card["explanation"]["alternatives"]]
    assert alternatives[0].startswith("Send Nordwind a payment reminder")
    assert card["proposed_action"] == {
        "kind": "apply_credit_line",
        "params": card["proposed_action"]["params"],
        "preview": card["proposed_action"]["preview"],
    }
    assert card["proposed_action"]["params"]["limit"] == {"amount": "30000.00", "currency": "PLN"}
    assert "SIMULATED" in card["proposed_action"]["preview"]
    assert card["explanation"]["generated_by"]["wording"] == "template"
    assert {"kind": "forecast", "id": "fc_20261121a"}.items() <= card["evidence"][0].items()
    assert contract.entity_errors("recommendation", card) == []


def test_a_gap_still_open_when_the_forecast_ends_gives_a_card_up_to_the_forecasts_last_day(db, world):
    # Regression: an open-ended gap (date_to null) crashed the agent.
    open_ended = forecast_fixture()
    open_ended["id"] = "fc_open_gap"
    open_ended["inputs_hash"] += "-open-gap"  # forecasts are unique by inputs_hash
    open_ended["alerts"][0]["date_to"] = None
    assert world.add("forecast", open_ended)

    on_forecast_updated(db, updated("fc_open_gap"), model=None)

    [card] = cards(world)
    # as_of_date 2026-11-21 + horizon_days 45 = 5 Jan, the forecast's last day: 36 days from 30 Nov
    assert card["summary"].startswith("From 30 Nov until at least 5 Jan, when the forecast ends, the accounts will be")
    estimated_cost = next(row for row in card["explanation"]["calculation"] if row["label"] == "Estimated cost")
    assert " x 36 days x " in estimated_cost["formula"]
    assert contract.entity_errors("recommendation", card) == []


def test_the_model_chooses_tools_and_writes_the_wording_with_engine_numbers_only(db, world):
    model = FakeModel(
        turn(tool_calls=[tool_call("get_forecast", {})]),
        turn(tool_calls=[tool_call("get_bank_price_list", {}, id="call_2")]),
        final("Open a 30,000 PLN credit line before 30 November",
              "Salaries of 58,000 PLN leave on 30 Nov before Nordwind pays.",
              ["Salaries of 58,000 PLN leave on 30 Nov", "Nordwind pays late", "Reimbursements of 5,169 PLN are owed"]),
    )

    on_forecast_updated(db, updated("fc_20261121a"), model=model)

    [card] = cards(world)
    assert card["summary"] == "Salaries of 58,000 PLN leave on 30 Nov before Nordwind pays."
    assert card["explanation"]["generated_by"]["wording"] != "template"
    assert card["explanation"]["generated_by"]["numbers"] == "finance-engine"
    assert card["proposed_action"]["params"]["limit"] == {"amount": "30000.00", "currency": "PLN"}
    assert [m["role"] for m in model.requests[-1]["messages"]].count("tool") == 2


def test_a_model_answer_with_an_invented_number_is_rejected_and_the_template_recommendation_stored(db, world):
    model = FakeModel(
        turn(tool_calls=[tool_call("get_forecast", {})]),
        final("Open a 45,000 PLN credit line before 30 November", "You need 45,000 PLN.", ["a", "b", "c"]),
    )

    on_forecast_updated(db, updated("fc_20261121a"), model=model)

    [card] = cards(world)
    assert card["title"] == "Open a 30,000 PLN credit line before 30 November"
    assert card["explanation"]["generated_by"]["wording"] == "template"


def test_a_model_timeout_still_gives_the_template_recommendation(db, world):
    on_forecast_updated(db, updated("fc_20261121a"), model=FakeModel(error=TimeoutError("model did not answer")))

    [card] = cards(world)
    assert card["explanation"]["generated_by"]["wording"] == "template"


def test_the_tool_loop_stops_after_six_calls(db, world):
    endless = FakeModel(*[turn(tool_calls=[tool_call("get_forecast", {}, id=f"c{i}")]) for i in range(20)])

    on_forecast_updated(db, updated("fc_20261121a"), model=endless)

    assert sum(1 for m in endless.requests[-1]["messages"] if m["role"] == "tool") <= 6
    assert cards(world)[0]["explanation"]["generated_by"]["wording"] == "template"


def test_the_same_alert_twice_gives_one_card_and_a_changed_alert_supersedes_it(db, world):
    on_forecast_updated(db, updated("fc_20261121a"), model=None)
    on_forecast_updated(db, updated("fc_20261121a"), model=None)
    assert len(cards(world)) == 1

    worse = forecast_fixture()
    worse.update(id="fc_worse", inputs_hash="other")
    worse["alerts"][0]["max_shortfall"] = {"amount": "9100.00", "currency": "PLN"}
    world.add("forecast", worse)
    on_forecast_updated(db, updated("fc_worse"), model=None)

    statuses = sorted((c["status"], c["subject"]["id"]) for c in cards(world))
    assert statuses == [("new", "fc_worse"), ("superseded", "fc_20261121a")]


def test_a_forecast_without_alerts_gives_no_card(db, world):
    calm = forecast_fixture()
    calm.update(id="fc_calm", inputs_hash="calm", alerts=[], first_negative_date=None)
    world.add("forecast", calm)

    on_forecast_updated(db, updated("fc_calm"), model=None)

    assert cards(world) == []


def test_a_model_answer_in_the_wrong_shape_gets_one_corrective_retry(db, world):
    model = FakeModel(
        turn(tool_calls=[tool_call("get_forecast", {})]),
        turn(content=json.dumps({"title": "Open a 30,000 PLN credit line before 30 November",
                                 "summary": "Salaries of 58,000 PLN leave on 30 Nov.", "why": "one string, not a list"})),
        final("Open a 30,000 PLN credit line before 30 November", "Salaries of 58,000 PLN leave on 30 Nov.",
              ["Salaries of 58,000 PLN leave on 30 Nov", "Nordwind pays late"]),
    )

    on_forecast_updated(db, updated("fc_20261121a"), model=model)

    [card] = cards(world)
    assert card["explanation"]["why"] == ["Salaries of 58,000 PLN leave on 30 Nov", "Nordwind pays late"]
    assert "why" in model.requests[-1]["messages"][-1]["content"]  # the retry names the problem


def test_the_template_card_is_stored_before_the_model_is_asked(db, world):
    seen_while_model_runs = []

    class SlowModel(FakeModel):
        def _create(self, **request):
            seen_while_model_runs.append([c["id"] for c in cards(world)])
            return super()._create(**request)

    on_forecast_updated(db, updated("fc_20261121a"), model=SlowModel(final("x" * 10, "y" * 20, ["a", "b"])))

    assert seen_while_model_runs[0] == ["rec_cl_fc_20261121a"]


def test_the_limit_and_the_stress_case_on_the_card_come_from_the_engine(db, world, monkeypatch):
    from backend.finance import engine

    money = lambda amount: {"amount": amount, "currency": "PLN"}  # noqa: E731
    stress = {"label": "Nordwind pays 21 Dec", "date": "2026-12-21", "balance": money("-46072.20")}
    monkeypatch.setattr(engine, "stress", lambda conn, company: stress)
    monkeypatch.setattr(engine, "credit_line", lambda conn, company: {"limit": money("50000.00")})
    on_forecast_updated(db, updated("fc_20261121a"), model=None)
    card = cards(world)[0]
    assert card["title"] == "Open a 50,000 PLN credit line before 30 November"
    assert card["proposed_action"]["params"]["limit"] == money("50000.00")
    calculation = {row["label"]: row["value"] for row in card["explanation"]["calculation"]}
    assert calculation["Stress case (Nordwind pays 21 Dec)"] == "-46,072.20 PLN on 21 Dec"
