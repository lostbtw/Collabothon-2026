"""Write and read events in the outbox (contracts/events.md). The envelope is contracts/schemas/event.schema.json.

`publish` is how role 5's code emits events. Role 2's queue (backend/queue/) owns claiming deliveries for workers;
`events_after` is the read used by the browser stream (SSE).
"""
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def new_event(type: str, company_id: str, payload: dict[str, Any], *, producer: str,
              correlation_id: str | None = None, causation_id: str | None = None) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": type,
        "occurred_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "company_id": company_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "producer": producer,
        "payload": payload,
    }


def publish(conn: psycopg.Connection, event: dict[str, Any], *, commit: bool = True) -> bool:
    """Append an event; a repeated id is ignored. Returns True when stored."""
    cur = conn.execute(
        """insert into outbox (id, type, company_id, correlation_id, causation_id, producer, payload, occurred_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (id) do nothing""",
        (event["id"], event["type"], event["company_id"], event.get("correlation_id"),
         event.get("causation_id"), event.get("producer") or "api", Jsonb(event["payload"]), event["occurred_at"]),
    )
    if commit:
        conn.commit()
    return cur.rowcount == 1


def events_after(conn: psycopg.Connection, seq: int, company_id: str | None = None, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
    """(seq, envelope) pairs with seq greater than the given one, oldest first."""
    rows = conn.execute(
        """select seq, id, type, occurred_at, company_id, correlation_id, causation_id, producer, payload
           from outbox where seq > %s and (%s::text is null or company_id = %s) order by seq limit %s""",
        (seq, company_id, company_id, limit),
    ).fetchall()
    out = []
    for seq_, id, type, occurred_at, company, corr, caus, producer, payload in rows:
        env = {"id": id, "type": type, "occurred_at": occurred_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "company_id": company, "correlation_id": corr, "causation_id": caus, "producer": producer,
               "payload": payload}
        out.append((seq_, {k: v for k, v in env.items() if v is not None}))
    return out
