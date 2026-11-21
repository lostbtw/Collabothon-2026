"""Seam: HTTP API. Duplicates the pipeline merged on its own appear in "What I did on my own"."""
from backend.db.events import new_event, publish
from backend.db.fixtures import load_fixtures, read
from backend.db.store import Store


def merge_copy(db, *, reason: str | None):
    """An e-mailed PDF copy of the hero receipt, merged into the photo the way role 3's pipeline does it."""
    golden = next(d for d in read("document") if d["id"] == "doc_rcpt412")
    copy = {**golden, "id": "doc_rcpt412pdf", "raw_item_ids": ["raw_mail412pdf"], "channel": "email",
            "status": "duplicate", "duplicate_of": "doc_rcpt412"}
    Store(db).add("document", copy, company_id="co_borsuk")
    if reason:
        publish(db, new_event("document.duplicate_detected", "co_borsuk",
                              {"document_id": copy["id"], "duplicate_of": "doc_rcpt412", "reason": reason},
                              producer="pipeline", correlation_id="raw_mail412pdf"))
    return copy


def activity(client):
    return client.get("/api/v1/activity", params={"company_id": "co_borsuk"}).json()["items"]


def test_a_merged_duplicate_is_listed_with_both_copies_and_the_reason(client, db):
    load_fixtures(db)
    merge_copy(db, reason="D1: same seller tax id, number and gross")

    [item] = [i for i in activity(client) if i["subject"] == {"type": "document", "id": "doc_rcpt412pdf"}]

    assert item["agent"] == "ingestion"
    assert item["text"] == ("Kept one copy of PARAGON 004512/11/2026 from ElektroMarkt Polska S.A. (SAMPLE): the "
                            "e-mailed PDF is a duplicate of the photo (D1: same seller tax id, number and gross)")
    assert [(e["id"], e["label"]) for e in item["evidence"]] == [("doc_rcpt412", "Kept copy"),
                                                                ("doc_rcpt412pdf", "Duplicate")]
    assert item["at"].endswith("Z")


def test_a_duplicate_without_its_event_is_still_listed(client, db):
    load_fixtures(db)
    copy = merge_copy(db, reason=None)

    [item] = [i for i in activity(client) if i["subject"]["id"] == copy["id"]]

    assert item["text"].endswith("is a duplicate of the photo")
    assert item["at"] == copy["created_at"]


def test_documents_that_are_not_duplicates_are_not_listed(client, db):
    load_fixtures(db)

    assert [i for i in activity(client) if i["subject"]["type"] == "document"] == []
