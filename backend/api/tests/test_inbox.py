"""Seam: HTTP API. The to-do lists approvals first, then single pieces of advice, never bulk advice."""
from backend.api import contract
from backend.db.fixtures import load_fixtures, read
from backend.db.store import Store


def advice(template, id, type):
    return {**template, "id": id, "type": type, "control_level": "recommendation", "status": "new",
            "severity": "info", "proposed_action": None}


def test_the_inbox_lists_approvals_then_single_advice_and_leaves_bulk_advice_out(client, db):
    load_fixtures(db)
    s = Store(db)
    template = next(r for r in read("recommendation") if r["company_id"] == "co_borsuk")
    s.add("recommendation", advice(template, "rec_nohedge", "info"), company_id="co_borsuk")
    s.add("recommendation", advice(template, "rec_private", "mark_private"), company_id="co_borsuk")
    s.add("recommendation", advice(template, "rec_whichpay", "missing_document"), company_id="co_borsuk")

    response = client.get("/api/v1/inbox", params={"company_id": "co_borsuk"})

    assert response.status_code == 200
    body = response.json()
    levels = [r["control_level"] for r in body["items"]]
    ids = [r["id"] for r in body["items"]]
    assert "rec_nohedge" in ids and "rec_private" not in ids and "rec_whichpay" not in ids
    assert "analysed_autonomously" not in levels
    assert levels == sorted(levels, key=lambda level: level != "approval_required")
    assert body["counts"]["approval_required"] == levels.count("approval_required")
    assert contract.errors(body, contract.response_schema("get", "/inbox", 200)) == []
