"""`uv run python -m backend agents`: the agent service. Handles the outbox deliveries of consumer group 'agents'.

match.suggested  -> ingestion card (5.10)
forecast.updated -> tax reserve card (5.10), credit-line card of the liquidity agent (5.6),
                    reminders for late client invoices (receivables), FX Shield cards per foreign-currency invoice (#47)

Claiming is role 2's backend/queue (contracts/events.md: SKIP LOCKED, done after commit, 3 failures -> dead).
"""
import logging
from collections.abc import Callable
from typing import Any

import psycopg

from backend.agents import fx, ingestion, liquidity, receivables
from backend import queue
from backend.settings import database_url

log = logging.getLogger("ordo.agents")
CONSUMER = "agents"
MAX_ATTEMPTS = 3

HANDLERS: dict[str, list[Callable[[psycopg.Connection, dict[str, Any]], Any]]] = {
    "match.suggested": [ingestion.on_match_suggested],
    "forecast.updated": [ingestion.on_forecast_updated, liquidity.on_forecast_updated, receivables.on_forecast_updated,
                        fx.on_forecast_updated],
}


def _handle(conn: psycopg.Connection, event: dict[str, Any]) -> None:
    for handler in HANDLERS.get(event["type"], []):
        handler(conn, event)


def process_pending(conn: psycopg.Connection, retry_after_seconds: int = 30) -> int:
    """Handle every claimable delivery once. Returns how many were handled successfully.
    `match.suggested` first: a new document's card must not wait behind a burst of forecast updates."""
    return queue.process_pending(conn, CONSUMER, lambda event: _handle(conn, event),
                                 retry_after_seconds=retry_after_seconds, max_attempts=MAX_ATTEMPTS,
                                 first_types=["match.suggested"])


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = queue.listen(database_url())
        log.info("agents: listening")
        while True:
            process_pending(conn)
            queue.wait(listener, timeout=5.0)  # wake on NOTIFY, or poll every 5 s
