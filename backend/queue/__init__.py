"""The worker side of the Postgres outbox (#35, D-07, contracts/events.md). Owner: role 2.

Every process that handles events (pipeline, extractor, finance, agents) claims its own deliveries the same way:

    from backend import queue
    handled = queue.process_pending(conn, "finance", lambda event: handle(conn, event))

- claim: one pending delivery of the consumer group, `FOR UPDATE SKIP LOCKED`, so two workers never take the same one;
  the attempt is counted and committed before the handler runs (a crash still counts);
- done: only after the handler committed its own writes (at-least-once delivery, handlers are idempotent);
- a failing handler is retried after `retry_after_seconds`; after `max_attempts` failures the delivery is `dead`, and a
  `raw_item.received` event marks its RawItem `failed` so the Sources page counts it;
- `wait(listener)` sleeps until the database announces a new event (LISTEN/NOTIFY) or the timeout passes.

The four loops this replaces behaved exactly like this; nothing about the order, the retries or the commits changed.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 3
RETRY_AFTER_SECONDS = 30
CHANNEL = "outbox"

log = logging.getLogger("ordo.queue")


def claim(conn: psycopg.Connection, consumer: str, *, retry_after_seconds: int = RETRY_AFTER_SECONDS,
          first_types: Iterable[str] = ()) -> tuple[dict[str, Any], int] | None:
    """The next pending delivery of `consumer` as (event envelope, attempt number), or None. Not committed: the caller
    commits (process_pending does it at once). `first_types` are taken before every other type, oldest first."""
    first = list(first_types)
    row = conn.execute(
        """select d.event_id, d.attempts, o.type, o.company_id, o.occurred_at, o.correlation_id, o.payload
           from outbox_delivery d join outbox o on o.id = d.event_id
           where d.consumer = %s and d.status = 'pending' and (d.locked_until is null or d.locked_until < now())
           order by (o.type = any(%s)) desc, o.seq limit 1 for update of d skip locked""",
        (consumer, first),
    ).fetchone()
    if row is None:
        return None
    event_id, attempts, type_, company, occurred_at, correlation, payload = row
    conn.execute(
        "update outbox_delivery set attempts = attempts + 1, locked_until = now() + make_interval(secs => %s) "
        "where event_id = %s and consumer = %s",
        (max(retry_after_seconds, 0), event_id, consumer),
    )
    event = {"id": event_id, "type": type_, "company_id": company, "correlation_id": correlation, "payload": payload,
             "occurred_at": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return event, attempts + 1


def finish(conn: psycopg.Connection, event_id: str, consumer: str, status: str) -> None:
    """Mark a delivery `done` or `dead`; not committed."""
    conn.execute("update outbox_delivery set status = %s, locked_until = null where event_id = %s and consumer = %s",
                 (status, event_id, consumer))


def mark_raw_item_failed(conn: psycopg.Connection, event: dict[str, Any], error: BaseException) -> None:
    """contracts/events.md rule 5: a dead `raw_item.received` leaves its RawItem `failed`, with the error."""
    if event.get("type") != "raw_item.received":
        return
    raw_id = (event.get("payload") or {}).get("raw_item_id")
    row = conn.execute("select doc from raw_items where id = %s", (raw_id,)).fetchone() if raw_id else None
    if row is None:
        return
    doc = {**row[0], "processing_status": "failed",
           "error": {"code": "processing_failed", "message": str(error)[:500] or error.__class__.__name__,
                     "retryable": True}}
    conn.execute("update raw_items set doc = %s where id = %s", (Jsonb(doc), raw_id))


def process_pending(conn: psycopg.Connection, consumer: str, handle: Callable[[dict[str, Any]], Any], *,
                    retry_after_seconds: int = RETRY_AFTER_SECONDS, max_attempts: int = MAX_ATTEMPTS,
                    first_types: Iterable[str] = (),
                    on_dead: Callable[[psycopg.Connection, dict[str, Any], BaseException], None] | None = mark_raw_item_failed,
                    name: str | None = None) -> int:
    """Handle every claimable delivery of `consumer` once. Returns how many were handled successfully."""
    label = name or consumer
    handled = 0
    while True:
        claimed = claim(conn, consumer, retry_after_seconds=retry_after_seconds, first_types=first_types)
        if claimed is None:
            conn.commit()
            return handled
        event, attempt = claimed
        conn.commit()  # the attempt counts even if the handler crashes the process
        try:
            handle(event)
            finish(conn, event["id"], consumer, "done")
            conn.commit()
            handled += 1
        except Exception as error:
            conn.rollback()
            log.exception("%s: %s %s failed (attempt %d)", label, event["type"], event["id"], attempt)
            if attempt >= max_attempts:
                try:
                    if on_dead is not None:
                        on_dead(conn, event, error)
                except Exception:  # noqa: BLE001 - the delivery must still end dead
                    conn.rollback()
                    log.exception("%s: could not record the failure of %s", label, event["id"])
                finish(conn, event["id"], consumer, "dead")
                conn.commit()


def listen(database_url: str) -> psycopg.Connection:
    """A separate autocommit connection subscribed to the outbox channel (pass it to `wait`)."""
    listener = psycopg.connect(database_url, autocommit=True)
    listener.execute(f"listen {CHANNEL}")
    return listener


def wait(listener: psycopg.Connection, timeout: float = 5.0) -> None:
    """Return when a new event is announced, or after `timeout` seconds (a poll for retries and missed notices)."""
    for _ in listener.notifies(timeout=timeout, stop_after=1):
        pass
