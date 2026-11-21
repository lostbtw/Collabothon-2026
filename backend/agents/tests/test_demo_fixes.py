"""Demo fixes: the chat's "ask a client to pay earlier" card, stale tax cards, and the demo reset."""
import copy

from backend.agents import demo_reset, ingestion
from backend.agents.chat import request_action
from backend.api import contract
from backend.db.fixtures import load_fixtures, read
from backend.db.store import Store


def forecast_fixture():
    return next(f for f in read("forecast") if f["id"] == "fc_20261121a")


def open_cards(db, **where):
    return Store(db).list("recommendation", company_id="co_borsuk", status=["new", "seen"], **where)


def test_asking_a_client_to_pay_earlier_drafts_the_reminder_e_mail(db):
    load_fixtures(db)

    result = request_action(db, "co_borsuk", "Ask Nordwind to pay the invoice earlier than 7 Dec", "payment")

    card = Store(db).get("recommendation", result["recommendation_id"])
    assert card["type"] == "chase_receivable" and card["agent"] == "liquidity"
    assert card["title"] == "Ask Nordwind to pay invoice FV/10/07 earlier"
    assert (card["control_level"], card["execution_mode"]) == ("approval_required", "simulated")
    assert card["proposed_action"]["kind"] == "send_email_draft"
    assert "Hello Nordwind team" in card["proposed_action"]["preview"]
    assert card["proposed_action"]["preview"].startswith("SIMULATED")
    assert contract.entity_errors("recommendation", card) == []
    again = request_action(db, "co_borsuk", "Remind Nordwind to pay sooner", "chase_receivable")
    assert again["recommendation_id"] == card["id"]  # one open reminder per invoice


def test_a_payment_request_naming_a_client_is_still_a_plain_inbox_note(db):
    load_fixtures(db)

    result = request_action(db, "co_borsuk", "Transfer 5,000 PLN to Nordwind now", "payment")

    assert Store(db).get("recommendation", result["recommendation_id"])["agent"] == "chat"


def test_a_tax_card_the_forecast_no_longer_has_leaves_the_to_do(db):
    load_fixtures(db)
    s = Store(db)
    forecast = forecast_fixture()
    s.put("forecast", forecast)
    stale = copy.deepcopy(next(r for r in read("recommendation") if r["company_id"] == "co_borsuk"))
    stale.update(id="rec_tax_reserve_c_ser_old", type="tax_reserve", agent="tax", status="new", approval_id=None)
    s.put("recommendation", stale)

    ingestion.on_forecast_updated(db, {"id": "evt_fc", "type": "forecast.updated", "occurred_at": "2026-11-21T10:15:03Z",
                                       "company_id": "co_borsuk", "payload": {"forecast_id": forecast["id"]}})

    assert [r["id"] for r in open_cards(db, type="tax_reserve")] == ["rec_tax_reserve_c_vat"]
    assert s.get("recommendation", "rec_tax_reserve_c_ser_old")["status"] == "superseded"


def test_demo_reset_clears_chat_cards_and_brings_back_a_credit_line(db):
    load_fixtures(db)
    s = Store(db)
    for card in open_cards(db, type="credit_line"):
        s.put("recommendation", {**card, "status": "executed_simulated"})
    note = request_action(db, "co_borsuk", "Transfer 5,000 PLN to Nordwind now", "payment")
    reminder = request_action(db, "co_borsuk", "Ask Nordwind to pay earlier", "chase_receivable")

    result = demo_reset.reset(db, "co_borsuk")

    assert set(result["chat_cards_removed"]) == {note["recommendation_id"], reminder["recommendation_id"]}
    [credit_line] = open_cards(db, type="credit_line")
    assert result["open_credit_line"] == credit_line["id"]
    assert contract.entity_errors("recommendation", credit_line) == []
    assert demo_reset.reset(db, "co_borsuk")["open_credit_line"] == credit_line["id"]  # a second run adds none


def test_without_usable_model_words_the_reminder_reply_explains_the_gap(db):
    load_fixtures(db)
    from backend.agents import chat

    reply = chat.answer(db, "co_borsuk", "Ask Nordwind to pay their invoice earlier", None, model=None)

    card = Store(db).get("recommendation", reply["created_recommendation_id"])
    assert card["type"] == "chase_receivable"
    assert card["title"] in reply["answer"] and "drafted a reminder" in reply["answer"]
    assert "cannot move money" not in reply["answer"]


class _Says:
    """A model that answers at once, without calling any tool."""

    def __init__(self, text):
        import json
        from types import SimpleNamespace as NS
        message = NS(tool_calls=None, content=json.dumps({"answer": text}))
        self.chat = NS(completions=NS(create=lambda **_: NS(choices=[NS(message=message)])))


def test_a_reminder_the_model_only_claims_is_made_for_real(db):
    load_fixtures(db)
    from backend.agents import chat

    reply = chat.answer(db, "co_borsuk", "How do we deal with the December shortage?", None,
                        model=_Says("You could ask Nordwind to pay earlier. I've added a reminder to your inbox."))

    card = Store(db).get("recommendation", reply["created_recommendation_id"])
    assert card["type"] == "chase_receivable" and "Nordwind" in card["title"]


def test_a_card_claim_with_nothing_behind_it_is_not_shown(db):
    load_fixtures(db)
    from backend.agents import chat

    reply = chat.answer(db, "co_borsuk", "How do we deal with the December shortage?", None,
                        model=_Says("Cut costs. I've created a card in your to-do for that."))

    assert "created a card" not in reply["answer"]
    assert not any(r["agent"] == "chat" and "Cut costs" in r["title"]
                   for r in Store(db).list("recommendation", company_id="co_borsuk"))


def test_a_reminder_reply_carries_no_money_guardrail_note(db):
    load_fixtures(db)
    from backend.agents import chat

    reply = chat.answer(db, "co_borsuk", "Ask Nordwind to pay their invoice earlier", None, model=None)

    assert reply["created_recommendation_id"] and reply["guardrail"] is None
