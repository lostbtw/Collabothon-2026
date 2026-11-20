"""Seam: HTTP API. The Recommendation/Approval state machine with simulated execution (5.4)."""
import pytest

from backend.api.recommendations import InvalidRecommendation, save_recommendation
from backend.db.events import events_after
from backend.db.fixtures import load_fixtures, read


@pytest.fixture
def demo(client, db):
    load_fixtures(db)
    return client


def events(db, type):
    return [e for _, e in events_after(db, 0, limit=1000) if e["type"] == type]


def fixture_rec(id):
    return next(r for r in read("recommendation") if r["id"] == id)


def test_approving_the_credit_line_with_a_lower_limit_executes_in_simulation_with_a_new_forecast(demo, db):
    before = demo.get("/api/v1/forecast/latest", params={"company_id": "co_borsuk"}).json()["id"]

    response = demo.post("/api/v1/recommendations/rec_cl01/decision", json={
        "decision": "approved_with_changes",
        "comment": "25k is enough",
        "changes": {"proposed_action.params.limit": {"amount": "25000.00", "currency": "PLN"}},
    })

    assert response.status_code == 200, response.text
    approval = response.json()
    assert approval["decision"] == "approved_with_changes"
    assert approval["execution"]["mode"] == "simulated"
    assert approval["execution"]["status"] == "done"
    assert approval["execution"]["reference"].startswith("SIM-CL-")
    assert "25,000" in approval["execution"]["result"]
    assert "SIMULATED" in approval["execution"]["result"]
    after = demo.get("/api/v1/forecast/latest", params={"company_id": "co_borsuk"}).json()["id"]
    assert after != before
    assert any(e["kind"] == "forecast" and e["id"] == after for e in approval["execution"]["effects"])
    assert demo.get("/api/v1/recommendations/rec_cl01").json()["status"] == "executed_simulated"
    assert [e["payload"]["approval_id"] for e in events(db, "approval.recorded")] == [approval["id"]]
    assert [e["payload"]["reference"] for e in events(db, "execution.simulated")] == [approval["execution"]["reference"]]


def test_the_approved_action_reaches_the_sandbox_bank(demo, sandbox_bank):
    """#36: the decision endpoint runs role 2's executor; the bank holds the application with the owner's limit."""
    approval = demo.post("/api/v1/recommendations/rec_cl01/decision", json={
        "decision": "approved_with_changes",
        "changes": {"proposed_action.params.limit": {"amount": "25000.00", "currency": "PLN"}},
    }).json()

    [done] = sandbox_bank.get("/admin/executions", headers={"Authorization": "Bearer test-bank-token"}).json()["executions"]
    assert done["type"] == "credit_line_application" and done["limit"] == "25000.00"
    assert done["reference"] == approval["execution"]["reference"]


def test_when_the_bank_is_down_the_decision_stands_and_the_card_shows_the_failure(demo, db, monkeypatch):
    import httpx

    import backend.executor.simulated as executor

    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(executor, "make_client",
                        lambda: httpx.Client(base_url="http://bank.invalid", transport=httpx.MockTransport(down)))
    approval = demo.post("/api/v1/recommendations/rec_cl01/decision", json={"decision": "approved"}).json()

    assert approval["execution"]["status"] == "failed"
    assert "unreachable" in approval["execution"]["result"]
    assert events(db, "execution.simulated") == []


def test_approving_the_reimbursement_decides_its_match_with_the_same_single_approval(demo, db):
    approval = demo.post("/api/v1/recommendations/rec_412/decision", json={"decision": "approved"}).json()

    decided = events(db, "match.decided")
    assert [(e["payload"]["match_id"], e["payload"]["status"], e["payload"]["approval_id"]) for e in decided] == [
        ("mat_412", "confirmed", approval["id"])]
    approvals = demo.get("/api/v1/approvals", params={"company_id": "co_borsuk"}).json()["items"]
    about_this_purchase = [a for a in approvals if a["subject_id"] in ("rec_412", "mat_412")]
    assert [a["id"] for a in about_this_purchase] == [approval["id"]]
    assert demo.get("/api/v1/matches", params={"company_id": "co_borsuk", "status": "confirmed"}).json()["items"][0]["id"] == "mat_412"


def test_approving_the_credit_line_decides_no_match_even_though_it_cites_one(demo, db):
    demo.post("/api/v1/recommendations/rec_cl01/decision", json={"decision": "approved"})

    assert events(db, "match.decided") == []


def test_a_rejection_records_an_approval_and_executes_nothing(demo, db):
    approval = demo.post("/api/v1/recommendations/rec_cl01/decision", json={"decision": "rejected"}).json()

    assert approval["decision"] == "rejected"
    assert approval["execution"]["status"] == "not_applicable"
    assert events(db, "execution.simulated") == []
    assert demo.get("/api/v1/recommendations/rec_cl01").json()["status"] == "rejected"


def test_a_decided_recommendation_cannot_be_decided_again(demo):
    demo.post("/api/v1/recommendations/rec_cl01/decision", json={"decision": "approved"})

    again = demo.post("/api/v1/recommendations/rec_cl01/decision", json={"decision": "approved"})

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_decidable"


def test_an_attempt_to_execute_for_real_is_refused(demo, db):
    response = demo.post("/api/v1/recommendations/rec_cl01/decision",
                         json={"decision": "approved_with_changes", "changes": {"execution_mode": "permitted"}})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "execution_not_permitted"
    assert events(db, "approval.recorded") == []


def test_a_change_outside_the_action_parameters_is_refused(demo):
    response = demo.post("/api/v1/recommendations/rec_cl01/decision",
                         json={"decision": "approved_with_changes", "changes": {"control_level": "analysed_autonomously"}})

    assert response.status_code == 422


@pytest.mark.parametrize("broken", [
    {"control_level": None},
    {"execution_mode": None},
    {"explanation": None},
    {"evidence": []},
    {"execution_mode": "permitted"},
])
def test_a_recommendation_without_its_labels_explanation_or_evidence_is_not_stored(db, broken):
    load_fixtures(db)
    rec = {**fixture_rec("rec_412"), "id": "rec_new", "subject": None}
    rec = {k: v for k, v in {**rec, **broken}.items() if v is not None}

    with pytest.raises(InvalidRecommendation):
        save_recommendation(db, rec)


def test_an_auto_confirmed_match_can_be_undone_from_its_activity_item(demo, db):
    item = next(i for i in demo.get("/api/v1/activity", params={"company_id": "co_borsuk"}).json()["items"]
                if i["subject"]["type"] == "match")

    undo = demo.post(f"/api/v1/matches/{item['subject']['id']}/decision", json={"decision": "rejected", "comment": "undo"})

    assert undo.status_code == 200
    assert undo.json()["decision"] == "rejected"
    assert [e["payload"]["status"] for e in events(db, "match.decided")] == ["rejected"]
    remaining = demo.get("/api/v1/activity", params={"company_id": "co_borsuk"}).json()["items"]
    assert item["subject"] not in [i["subject"] for i in remaining]


# --- review fixes -------------------------------------------------------------------------------------------------

def test_approving_a_card_about_a_document_decides_no_match_unless_it_is_an_ingestion_card(demo, db):
    """rec_fx01 (FX hedge) is about invoice doc_fvlake01; a pending Match on that invoice is not its decision."""
    from backend.db.store import Store
    s = Store(db)
    pending = {**next(m for m in read("match") if m["id"] == "mat_412"), "id": "mat_lake", "document_id": "doc_fvlake01"}
    s.add("match", pending, company_id="co_borsuk")

    demo.post("/api/v1/recommendations/rec_fx01/decision", json={"decision": "approved"})

    assert events(db, "match.decided") == []
    assert s.get("match", "mat_lake")["status"] == "suggested"


def test_dismissing_a_hint_leaves_its_match_alone(demo, db):
    from backend.db.store import Store
    s = Store(db)
    hint = {**fixture_rec("rec_412"), "id": "rec_hint", "type": "mark_private", "control_level": "recommendation",
            "execution_mode": "none", "proposed_action": None}
    s.put("recommendation", hint)
    s.put("recommendation", {**fixture_rec("rec_412"), "status": "superseded"})  # make the hint the only open card

    response = demo.post("/api/v1/recommendations/rec_hint/decision", json={"decision": "rejected"})

    assert response.status_code == 200
    assert events(db, "match.decided") == []
    assert s.get("match", "mat_412")["status"] == "suggested"


def test_deciding_the_match_directly_closes_its_card_so_the_purchase_is_never_approved_twice(demo, db):
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})

    assert demo.get("/api/v1/recommendations/rec_412").json()["status"] == "approved"
    again = demo.post("/api/v1/recommendations/rec_412/decision", json={"decision": "approved"})
    assert again.status_code == 409
    assert events(db, "execution.simulated") == []


def test_a_decided_match_cannot_be_decided_again(demo):
    demo.post("/api/v1/matches/mat_412/decision", json={"decision": "approved"})

    again = demo.post("/api/v1/matches/mat_412/decision", json={"decision": "rejected"})

    assert again.status_code == 409
