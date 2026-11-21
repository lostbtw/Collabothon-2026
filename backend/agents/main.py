"""`python -m backend agents`: consumer group 'agents'; HANDLERS maps events to cards."""
import logging
from collections.abc import Callable
from typing import Any

import psycopg

from backend.agents import fx, ingestion, liquidity, receivables
from backend import queue, tracing
from backend.settings import database_url

log = logging.getLogger("ordo.agents")
CONSUMER = "agents"
MAX_ATTEMPTS = 3
EXPERIMENT = "ordo-agents"

HANDLERS: dict[str, list[Callable[[psycopg.Connection, dict[str, Any]], Any]]] = {
    "match.suggested": [ingestion.on_match_suggested],
    "forecast.updated": [ingestion.on_forecast_updated, liquidity.on_forecast_updated, receivables.on_forecast_updated,
                        fx.on_forecast_updated],
}


def _handle(conn: psycopg.Connection, event: dict[str, Any]) -> None:
    for handler in HANDLERS.get(event["type"], []):
        handler(conn, event)


def process_pending(conn: psycopg.Connection, retry_after_seconds: int = 30) -> int:
    """Handle each claimable delivery once; `match.suggested` first so receipts never wait."""
    return queue.process_pending(conn, CONSUMER, lambda event: _handle(conn, event),
                                 retry_after_seconds=retry_after_seconds, max_attempts=MAX_ATTEMPTS,
                                 first_types=["match.suggested"])


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    tracing.setup(EXPERIMENT)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = queue.listen(database_url())
        log.info("agents: listening")
        while True:
            process_pending(conn)
            queue.wait(listener, timeout=5.0)  # wake on NOTIFY, or poll every 5 s
