"""`python -m backend finance`: the finance process (role 4). Serves the outbox consumer group `finance`
(backend/finance/handlers.py says which events do what).

Claiming follows contracts/events.md and backend/pipeline/main.py (SKIP LOCKED, done after commit,
3 failures -> dead). When role 2's backend/queue library lands, this loop switches to it.
Event types without a handler are marked done, so the group's queue does not grow.

Environment: ORDO_DATABASE_URL (backend/settings.py).
"""
import logging

import psycopg

from backend.settings import database_url

from .handlers import HANDLERS

log = logging.getLogger("ordo.finance")
CONSUMER = "finance"
MAX_ATTEMPTS = 3


def _claim(conn: psycopg.Connection, retry_after_seconds: int):
    row = conn.execute(
        """select d.event_id, d.attempts, o.type, o.company_id, o.correlation_id, o.payload
           from outbox_delivery d join outbox o on o.id = d.event_id
           where d.consumer = %s and d.status = 'pending' and (d.locked_until is null or d.locked_until < now())
           order by o.seq limit 1 for update of d skip locked""",
        (CONSUMER,),
    ).fetchone()
    if row is None:
        return None
    event_id, attempts, type_, company, correlation, payload = row
    conn.execute(
        "update outbox_delivery set attempts = attempts + 1, locked_until = now() + make_interval(secs => %s) "
        "where event_id = %s and consumer = %s", (max(retry_after_seconds, 0), event_id, CONSUMER))
    event = {"id": event_id, "type": type_, "company_id": company, "correlation_id": correlation, "payload": payload}
    return event, attempts + 1


def _finish(conn: psycopg.Connection, event_id: str, status: str) -> None:
    conn.execute("update outbox_delivery set status = %s, locked_until = null where event_id = %s and consumer = %s",
                 (status, event_id, CONSUMER))
    conn.commit()


def process_pending(conn: psycopg.Connection, retry_after_seconds: int = 30) -> int:
    """Handle every claimable `finance` delivery once. Returns how many succeeded."""
    handled = 0
    while True:
        claimed = _claim(conn, retry_after_seconds)
        if claimed is None:
            conn.commit()
            return handled
        event, attempt = claimed
        conn.commit()
        try:
            for handler in HANDLERS.get(event["type"], []):
                handler(conn, event)
            _finish(conn, event["id"], "done")
            handled += 1
        except Exception:
            conn.rollback()
            log.exception("finance: %s %s failed (attempt %d)", event["type"], event["id"], attempt)
            if attempt >= MAX_ATTEMPTS:
                _finish(conn, event["id"], "dead")


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = psycopg.connect(database_url(), autocommit=True)
        listener.execute("listen outbox")
        log.info("finance: listening (%s)", CONSUMER)
        while True:
            process_pending(conn)
            for _ in listener.notifies(timeout=5.0, stop_after=1):  # wake on NOTIFY, or poll every 5 s
                pass
