"""Seam: HTTP API. A corrected Document goes back to the matcher (R3·3.6 #42)."""
from backend.db.events import events_after
from backend.db.fixtures import load_fixtures


def test_correcting_a_document_publishes_document_extracted_so_the_matcher_reruns(client, db):
    load_fixtures(db)
    before = client.get("/api/v1/documents/doc_pixel11").json()["document"]

    response = client.patch("/api/v1/documents/doc_pixel11",
                            json={"category_suggestion": {"category": "software_subscriptions"}})

    assert response.status_code == 200, response.text
    extracted = [e for _, e in events_after(db, 0, limit=1000) if e["type"] == "document.extracted" and e["producer"] == "api"]
    assert len(extracted) == 1
    event = extracted[0]
    assert event["company_id"] == before["company_id"]
    assert event["payload"] == {"document_id": "doc_pixel11", "status": before["status"],
                                "gross": before["totals"]["gross"], "seller": before["seller"]["name"],
                                "flags": before.get("flags", [])}
    approval = next(e for _, e in events_after(db, 0, limit=1000) if e["type"] == "approval.recorded")
    assert event["causation_id"] == approval["payload"]["approval_id"]


def test_a_rejected_correction_publishes_nothing(client, db):
    load_fixtures(db)

    response = client.patch("/api/v1/documents/doc_pixel11", json={"number": "X-1"})

    assert response.status_code == 422
    assert not [e for _, e in events_after(db, 0, limit=1000) if e["type"] == "document.extracted" and e["producer"] == "api"]
