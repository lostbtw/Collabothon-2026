"""Seam: GET /api/v1/events/stream (SSE)."""
import json
import threading
import time

from backend.api import contract
from backend.db.events import new_event, publish


def read_events(response, count):
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
            if len(events) == count:
                break
    return events


def test_stream_replays_the_five_fixture_events_in_order(client):
    with client.stream("GET", "/api/v1/events/stream", params={"company_id": "co_borsuk", "max_events": 5}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = read_events(r, 5)

    assert [e["id"] for e in events] == ["evt_9001", "evt_9002", "evt_9003", "evt_9004", "evt_9005"]
    for e in events:
        assert contract.errors(e, {"$ref": "./schemas/event.schema.json"}) == []


def test_stream_relays_new_outbox_events_after_the_replay(client, db, monkeypatch):
    monkeypatch.setenv("ORDO_SSE_REPLAY_FIXTURES", "0")
    event = new_event("recommendation.created", "co_borsuk",
                      {"recommendation_id": "rec_412", "type": "reimburse_employee", "control_level": "approval_required"},
                      producer="agents")
    publish(db, event)

    def publish_later():
        time.sleep(0.5)
        later = new_event("forecast.updated", "co_borsuk", {"forecast_id": "fc_1"}, producer="finance")
        publish(db, later)

    threading.Thread(target=publish_later).start()
    with client.stream("GET", "/api/v1/events/stream", params={"company_id": "co_borsuk", "max_events": 1}) as r:
        events = read_events(r, 1)

    assert events[0]["type"] == "forecast.updated"
