"""Seam: the outbox table as role 2's queue code and every consumer see it."""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def insert_event(db, event):
    db.execute(
        """insert into outbox (id, type, company_id, correlation_id, causation_id, producer, payload, occurred_at)
           values (%(id)s, %(type)s, %(company_id)s, %(correlation_id)s, %(causation_id)s, %(producer)s, %(payload)s, %(occurred_at)s)
           on conflict (id) do nothing""",
        {**{"correlation_id": None, "causation_id": None, "producer": "test"}, **event, "payload": Jsonb(event["payload"])},
    )
    db.commit()


def consumers_of(db, event_id):
    return {r[0] for r in db.execute("select consumer from outbox_delivery where event_id = %s", (event_id,))}


def test_an_event_is_delivered_to_its_consumers_and_the_browser(db):
    events = json.loads((FIXTURES / "event.json").read_text(encoding="utf-8"))
    match_suggested = next(e for e in events if e["type"] == "match.suggested")

    insert_event(db, match_suggested)

    assert consumers_of(db, match_suggested["id"]) == {"agents", "sse"}


def test_the_same_event_twice_is_delivered_once(db):
    events = json.loads((FIXTURES / "event.json").read_text(encoding="utf-8"))
    insert_event(db, events[0])
    insert_event(db, events[0])

    count = db.execute("select count(*) from outbox_delivery where event_id = %s", (events[0]["id"],)).fetchone()[0]
    assert count == len(consumers_of(db, events[0]["id"]))
