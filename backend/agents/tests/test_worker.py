"""Seam: the agents process. Pending outbox deliveries for consumer 'agents' are handled once."""
from backend.agents.main import process_pending
from backend.db.events import new_event, publish
from backend.db.fixtures import read
from backend.db.seed import seed
from backend.db.store import Store


def delivery_status(db, event_id):
    return db.execute("select status, attempts from outbox_delivery where event_id = %s and consumer = 'agents'",
                      (event_id,)).fetchone()


def test_a_suggested_match_in_the_queue_becomes_a_card_and_the_delivery_is_done(db):
    seed(db)
    s = Store(db)
    s.add("document", next(d for d in read("document") if d["id"] == "doc_rcpt412"))
    s.add("match", next(m for m in read("match") if m["id"] == "mat_412"), company_id="co_borsuk")
    event = new_event("match.suggested", "co_borsuk", {"match_id": "mat_412", "document_id": "doc_rcpt412", "score": 0.86},
                      producer="matcher")
    publish(db, event)

    assert process_pending(db) == 1
    assert process_pending(db) == 0

    assert [r["type"] for r in s.list("recommendation")] == ["reimburse_employee"]
    assert delivery_status(db, event["id"]) == ("done", 1)


def test_a_failing_event_is_retried_then_marked_dead(db):
    seed(db)
    event = new_event("forecast.updated", "co_borsuk", {}, producer="finance")  # no forecast_id: the handler fails
    publish(db, event)

    for _ in range(3):
        process_pending(db, retry_after_seconds=0)

    assert delivery_status(db, event["id"]) == ("dead", 3)


def test_a_suggested_match_is_handled_before_an_earlier_forecast_update(db, monkeypatch):
    from backend.agents import main as worker

    seed(db)
    handled = []
    monkeypatch.setattr(worker, "HANDLERS", {"forecast.updated": [lambda c, e: handled.append(e["type"])],
                                             "match.suggested": [lambda c, e: handled.append(e["type"])]})
    publish(db, new_event("forecast.updated", "co_borsuk", {"forecast_id": "fc_x"}, producer="finance"))
    publish(db, new_event("match.suggested", "co_borsuk", {"match_id": "mat_x"}, producer="matcher"))

    process_pending(db)

    assert handled == ["match.suggested", "forecast.updated"]
