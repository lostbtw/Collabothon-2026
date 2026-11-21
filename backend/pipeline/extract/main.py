import functools
import logging
import os

import psycopg

from backend import queue
from backend import tracing
from backend.settings import database_url

from . import docling, extract_document, model
from .worker import CONSUMER, Extract, fail, handle

log = logging.getLogger("ordo.extractor")
MAX_ATTEMPTS = 3
RETRY_AFTER_SECONDS = int(os.environ.get("ORDO_EXTRACT_RETRY_SECONDS", "150"))
EXPERIMENT = "ordo-extraction"


def _handle(conn: psycopg.Connection, event: dict, extract: Extract) -> None:
    if event["type"] == "raw_item.received":
        outcome = handle(conn, event, extract)
        if outcome != "skipped":
            log.info("extractor: %s %s", event["payload"]["raw_item_id"], outcome)


def process_pending(conn: psycopg.Connection, extract: Extract,
                    retry_after_seconds: int = RETRY_AFTER_SECONDS) -> int:
    """After MAX_ATTEMPTS failed claims `fail` records the error on the RawItem."""
    return queue.process_pending(conn, CONSUMER, lambda event: _handle(conn, event, extract),
                                 retry_after_seconds=retry_after_seconds, max_attempts=MAX_ATTEMPTS,
                                 on_dead=fail, name="extractor")


def default_extract() -> Extract:
    return functools.partial(extract_document, docling_client=docling.default_client(),
                             llm_client=model.default_client())


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    tracing.setup(EXPERIMENT)
    extract = default_extract()
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = queue.listen(database_url())
        log.info("extractor: listening (%s)", CONSUMER)
        while True:
            process_pending(conn, extract)
            queue.wait(listener, timeout=5.0)
