from backend.agents.liquidity import on_forecast_updated
from backend.agents.tests.test_liquidity_agent import FakeModel, cards, final, tool_call, turn, updated, world  # noqa: F401


def test_accepted_wording_is_one_trace_and_the_card_carries_its_id(db, world, traced):
    model = FakeModel(
        turn(tool_calls=[tool_call("get_forecast", {})]),
        final("Open a 30,000 PLN credit line before 30 November", "Salaries of 58,000 PLN leave on 30 Nov.",
              ["Salaries of 58,000 PLN leave on 30 Nov", "Nordwind pays late", "Reimbursements are owed"]),
    )

    on_forecast_updated(db, updated("fc_20261121a"), model=model)

    [card] = cards(world)
    assert card["explanation"]["generated_by"]["trace_id"] == "tr-test"
    assert card["explanation"]["generated_by"]["wording"] != "template"
    assert [(name, depth) for name, depth, _ in traced.spans] == [("liquidity.wording", 0)]
    assert traced.tags == {"agent": "liquidity", "company_id": "co_borsuk", "recommendation_id": card["id"],
                           "outcome": "accepted"}


def test_rejected_wording_keeps_the_template_text_but_the_card_still_links_the_trace(db, world, traced):
    model = FakeModel(
        turn(tool_calls=[tool_call("get_forecast", {})]),
        final("Open a 45,000 PLN credit line before 30 November", "You need 45,000 PLN.", ["a", "b", "c"]),
    )

    on_forecast_updated(db, updated("fc_20261121a"), model=model)

    [card] = cards(world)
    assert card["title"] == "Open a 30,000 PLN credit line before 30 November"
    assert card["explanation"]["generated_by"]["wording"] == "template"
    assert card["explanation"]["generated_by"]["trace_id"] == "tr-test"
    assert traced.tags["outcome"] == "rejected_numbers"
    assert "45" in traced.tags["invented_numbers"]
    assert traced.outputs["liquidity.wording"]["accepted"] is False


def test_a_model_that_never_answers_is_traced_as_no_answer(db, world, traced):
    on_forecast_updated(db, updated("fc_20261121a"), model=FakeModel(error=TimeoutError("model did not answer")))

    [card] = cards(world)
    assert card["explanation"]["generated_by"]["trace_id"] == "tr-test"
    assert traced.tags["outcome"] == "no_answer"


def test_without_a_model_the_card_has_no_trace(db, world, traced):
    on_forecast_updated(db, updated("fc_20261121a"), model=None)

    [card] = cards(world)
    assert card["explanation"]["generated_by"]["trace_id"] is None
    assert traced.spans == []
