import functools
import logging
import os

import psycopg

from backend.settings import database_url

from . import docling, extract_document, model
from .worker import CONSUMER, Extract, fail, handle

log = logging.getLogger("ordo.extractor")
MAX_ATTEMPTS = 3
RETRY_AFTER_SECONDS = int(os.environ.get("ORDO_EXTRACT_RETRY_SECONDS", "150"))


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


def process_pending(conn: psycopg.Connection, extract: Extract,
                    retry_after_seconds: int = RETRY_AFTER_SECONDS) -> int:
    handled = 0
    while True:
        claimed = _claim(conn, retry_after_seconds)
        if claimed is None:
            conn.commit()
            return handled
        event, attempt = claimed
        conn.commit()
        try:
            if event["type"] == "raw_item.received":
                outcome = handle(conn, event, extract)
                if outcome != "skipped":
                    log.info("extractor: %s %s", event["payload"]["raw_item_id"], outcome)
            _finish(conn, event["id"], "done")
            handled += 1
        except Exception as error:
            conn.rollback()
            log.exception("extractor: %s %s failed (attempt %d)", event["type"], event["id"], attempt)
            if attempt >= MAX_ATTEMPTS:
                fail(conn, event, error)
                _finish(conn, event["id"], "dead")


def default_extract() -> Extract:
    return functools.partial(extract_document, docling_client=docling.default_client(),
                             llm_client=model.default_client())


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    extract = default_extract()
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = psycopg.connect(database_url(), autocommit=True)
        listener.execute("listen outbox")
        log.info("extractor: listening (%s)", CONSUMER)
        while True:
            process_pending(conn, extract)
            for _ in listener.notifies(timeout=5.0, stop_after=1):
                pass
