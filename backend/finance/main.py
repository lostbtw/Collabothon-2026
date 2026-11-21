"""`python -m backend finance`: the finance process, consumer group `finance`; events without a handler are marked done."""
import logging

import psycopg

from backend import queue
from backend.settings import database_url

from .handlers import DEBOUNCE_SECONDS, HANDLERS, recompute_due

log = logging.getLogger("ordo.finance")
CONSUMER = "finance"
MAX_ATTEMPTS = 3


def _handle(conn: psycopg.Connection, event: dict) -> None:
    for handler in HANDLERS.get(event["type"], []):
        handler(conn, event)


def process_pending(conn: psycopg.Connection, retry_after_seconds: int = 30) -> int:
    """Handle every claimable `finance` delivery once. Returns how many succeeded."""
    return queue.process_pending(conn, CONSUMER, lambda event: _handle(conn, event),
                                 retry_after_seconds=retry_after_seconds, max_attempts=MAX_ATTEMPTS)


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = queue.listen(database_url())
        log.info("finance: listening (%s)", CONSUMER)
        while True:
            process_pending(conn)
            recompute_due(conn)  # debounce: 2 s after a company's last input event
            queue.wait(listener, timeout=DEBOUNCE_SECONDS)  # wake on NOTIFY, or poll
