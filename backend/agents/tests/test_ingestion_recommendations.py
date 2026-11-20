"""Seam: the agent service's event handlers. match.suggested / forecast.updated -> inbox Recommendation (5.10)."""
import copy
import time

import pytest

from backend.agents.ingestion import on_forecast_updated, on_match_suggested
from backend.api import contract
from backend.db.fixtures import read
from backend.db.seed import seed
from backend.db.store import Store


def fixture(entity, id):
    return copy.deepcopy(next(i for i in read(entity) if i["id"] == id))


def match_suggested(match_id, document_id, score=0.86):
    return {"id": f"evt_{match_id}", "type": "match.suggested", "occurred_at": "2026-11-21T10:14:55Z",
            "company_id": "co_borsuk", "producer": "matcher",
            "payload": {"match_id": match_id, "document_id": document_id, "score": score}}


@pytest.fixture
def world(db):
    seed(db)
    s = Store(db)
    for entity, id in [("document", "doc_rcpt412"), ("document", "doc_pixel11"), ("transaction", "txn_731"),
                       ("match", "mat_412")]:
        s.add(entity, fixture(entity, id), company_id="co_borsuk")
    return s


def recommendations(s):
    return s.list("recommendation", company_id="co_borsuk")


def test_the_hero_match_becomes_the_reimbursement_card_within_a_second(db, world):
    started = time.monotonic()
    on_match_suggested(db, match_suggested("mat_412", "doc_rcpt412"))
    elapsed = time.monotonic() - started

    [rec] = recommendations(world)
    assert elapsed < 1.0
    assert rec["type"] == "reimburse_employee"
    assert rec["title"].startswith("Pay Jan back 1,299.00 PLN")
    assert (rec["control_level"], rec["execution_mode"]) == ("approval_required", "simulated")
    assert rec["proposed_action"]["kind"] == "create_payment_draft"
    assert rec["proposed_action"]["params"]["amount"] == {"amount": "1299.00", "currency": "PLN"}
    assert rec["proposed_action"]["params"]["to"] == "per_jan"
    assert rec["proposed_action"]["params"]["pay_on"] == "2026-11-30"
    assert "SIMULATED" in rec["proposed_action"]["preview"]
    assert rec["subject"]["id"] == "doc_rcpt412"
    assert {("document", "doc_rcpt412"), ("match", "mat_412"), ("rule", "PL-VAT-01")} <= {(e["kind"], e["id"]) for e in rec["evidence"]}
    assert any("242.90 PLN" == row["value"] for row in rec["explanation"]["calculation"])
    assert rec["explanation"]["generated_by"] == {"numbers": "finance-engine", "wording": "template", "trace_id": None}


def test_a_086_company_paid_match_without_tax_consequence_asks_to_confirm_with_reasons_and_alternatives(db, world):
    pixel = fixture("match", "mat_pixel11")
    pixel.update(status="suggested", score=0.86, paid_by="company_account",
                 consequences={"vat_deductible": True, "rule_ids": []})
    world.add("match", pixel, company_id="co_borsuk")
    look_alike = fixture("transaction", "txn_731")  # another unmatched card payment of about the same amount
    look_alike.update(id="txn_pln_000732", external_id="E000000732", booking_date="2026-11-21",
                      amount={"amount": "-178.40", "currency": "PLN"}, amount_base={"amount": "-178.40", "currency": "PLN"},
                      match_status="unmatched", recurring_series_id=None)
    world.add("transaction", look_alike, company_id="co_borsuk")

    on_match_suggested(db, match_suggested("mat_pixel11", "doc_pixel11"))

    [rec] = recommendations(world)
    assert rec["type"] == "confirm_match"
    assert rec["control_level"] == "approval_required"
    assert rec["subject"] == {"kind": "match", "id": "mat_pixel11", "label": rec["subject"]["label"]}
    assert rec["explanation"]["why"] == [r["detail"] for r in pixel["reasons"]]
    assert rec["explanation"]["confidence"] == 0.86
    assert any("txn_pln_000732" in a["label"] for a in rec["explanation"]["alternatives"])


@pytest.mark.parametrize("change,expected_type,control_level", [
    ({"paid_by": "employee_private"}, "reimburse_employee", "approval_required"),
    ({"paid_by": "company_account", "score": 0.95, "consequences": {"vat_deductible": False, "rule_ids": ["PL-VAT-01"]}},
     "request_company_invoice", "recommendation"),
    ({"paid_by": "company_account", "consequences": {"vat_deductible": True, "rule_ids": ["PL-PRIV-01"]}},
     "mark_private", "recommendation"),
    ({"paid_by": "unknown", "score": 0.4, "consequences": {"vat_deductible": None, "rule_ids": []}},
     "missing_document", "recommendation"),
    ({"paid_by": "owner_private", "consequences": {"vat_deductible": False, "rule_ids": ["PL-VAT-01"]}},
     "confirm_match", "approval_required"),
])
def test_every_kind_of_card_carries_both_badges_and_evidence(db, world, change, expected_type, control_level):
    match = fixture("match", "mat_412")
    match.update(id="mat_case", **change)
    if change["paid_by"] != "employee_private":
        match.update(payer=None)
    world.add("match", {**match, "document_id": "doc_pixel11"}, company_id="co_borsuk")

    on_match_suggested(db, match_suggested("mat_case", "doc_pixel11"))

    [rec] = [r for r in recommendations(world)]
    assert rec["type"] == expected_type
    assert rec["control_level"] == control_level
    assert rec["execution_mode"] in {"none", "simulated"}
    assert rec["evidence"]
    assert contract.entity_errors("recommendation", rec) == []


def test_the_same_event_twice_creates_one_card(db, world):
    on_match_suggested(db, match_suggested("mat_412", "doc_rcpt412"))
    on_match_suggested(db, match_suggested("mat_412", "doc_rcpt412"))

    assert len(recommendations(world)) == 1


def test_an_auto_confirmed_match_needs_no_card(db, world):
    auto = fixture("match", "mat_pixel11")
    world.add("match", auto, company_id="co_borsuk")

    on_match_suggested(db, match_suggested("mat_pixel11", "doc_pixel11", score=0.97))

    assert recommendations(world) == []


def test_upcoming_vat_in_the_forecast_becomes_a_tax_reserve_card(db, world):
    forecast = fixture("forecast", "fc_20261121a")
    world.add("forecast", forecast)

    on_forecast_updated(db, {"id": "evt_fc", "type": "forecast.updated", "occurred_at": "2026-11-21T10:15:03Z",
                             "company_id": "co_borsuk", "payload": {"forecast_id": forecast["id"]}})

    [rec] = recommendations(world)
    assert rec["type"] == "tax_reserve"
    assert rec["title"] == "Set aside 14,300 PLN for VAT on the 25th"
    assert (rec["control_level"], rec["execution_mode"]) == ("approval_required", "simulated")
    assert rec["proposed_action"]["kind"] == "move_to_tax_pocket"
    assert rec["proposed_action"]["params"]["amount"] == {"amount": "14300.00", "currency": "PLN"}
    assert contract.entity_errors("recommendation", rec) == []
