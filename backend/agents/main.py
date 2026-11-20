"""`uv run python -m backend agents`: the agent service. Handles the outbox deliveries of consumer group 'agents'.

match.suggested  -> ingestion card (5.10)
forecast.updated -> tax reserve card (5.10), credit-line card of the liquidity agent (5.6)

Claiming follows contracts/events.md (SKIP LOCKED, done after commit, 3 failures -> dead). When role 2's
backend/queue library lands, this loop switches to it.
"""
import logging
from collections.abc import Callable
from typing import Any

import psycopg

from backend.agents import ingestion, liquidity
from backend.settings import database_url

log = logging.getLogger("ordo.agents")
CONSUMER = "agents"
MAX_ATTEMPTS = 3

HANDLERS: dict[str, list[Callable[[psycopg.Connection, dict[str, Any]], Any]]] = {
    "match.suggested": [ingestion.on_match_suggested],
    "forecast.updated": [ingestion.on_forecast_updated, liquidity.on_forecast_updated],
}


def _claim(conn: psycopg.Connection, retry_after_seconds: int) -> tuple[dict[str, Any], int] | None:
    row = conn.execute(
        """select d.event_id, d.attempts, o.type, o.company_id, o.occurred_at, o.correlation_id, o.payload
           from outbox_delivery d join outbox o on o.id = d.event_id
           where d.consumer = %s and d.status = 'pending' and (d.locked_until is null or d.locked_until < now())
           order by o.seq limit 1 for update of d skip locked""",
        (CONSUMER,),
    ).fetchone()
    if row is None:
        return None
    event_id, attempts, type, company, occurred_at, correlation, payload = row
    conn.execute(
        "update outbox_delivery set attempts = attempts + 1, locked_until = now() + make_interval(secs => %s) "
        "where event_id = %s and consumer = %s",
        (max(retry_after_seconds, 0), event_id, CONSUMER),
    )
    event = {"id": event_id, "type": type, "company_id": company, "correlation_id": correlation, "payload": payload,
             "occurred_at": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return event, attempts + 1


def process_pending(conn: psycopg.Connection, retry_after_seconds: int = 30) -> int:
    """Handle every claimable delivery once. Returns how many were handled successfully."""
    handled = 0
    while True:
        claimed = _claim(conn, retry_after_seconds)
        if claimed is None:
            conn.commit()
            return handled
        event, attempt = claimed
        conn.commit()  # the attempt counts even if the handler crashes the process
        try:
            for handler in HANDLERS.get(event["type"], []):
                handler(conn, event)
            conn.execute("update outbox_delivery set status = 'done', locked_until = null where event_id = %s and consumer = %s",
                         (event["id"], CONSUMER))
            conn.commit()
            handled += 1
        except Exception:
            conn.rollback()
            log.exception("agents: %s %s failed (attempt %d)", event["type"], event["id"], attempt)
            if attempt >= MAX_ATTEMPTS:
                conn.execute("update outbox_delivery set status = 'dead' where event_id = %s and consumer = %s",
                             (event["id"], CONSUMER))
                conn.commit()


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = psycopg.connect(database_url(), autocommit=True)
        listener.execute("listen outbox")
        log.info("agents: listening")
        while True:
            process_pending(conn)
            for _ in listener.notifies(timeout=5.0, stop_after=1):  # wake on NOTIFY, or poll every 5 s
                pass
