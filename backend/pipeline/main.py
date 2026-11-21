"""`python -m backend pipeline`: the pipeline process (role 3). Serves the outbox consumer groups `normaliser` and
`matcher` (backend/pipeline/handlers.py says which events do what).

Claiming is role 2's backend/queue (contracts/events.md: SKIP LOCKED, done after commit, 3 failures -> dead).

Environment: ORDO_DATABASE_URL (backend/settings.py); ORDO_RAW_DIR = where pvc://raw/ is mounted (default /data/raw).
"""
import logging
import os
import time
from pathlib import Path
from typing import Any

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store
from backend import queue
from backend.settings import database_url

from .counterparty import model_chooser
from .handlers import HANDLERS, PRODUCER, Context, default_rates, rematch, sweep

log = logging.getLogger("ordo.pipeline")
MAX_ATTEMPTS = 3
SWEEP_SECONDS = int(os.environ.get("ORDO_PIPELINE_SWEEP_SECONDS", "60"))
_CHOOSE = model_chooser()  # the cluster's model for category/kind when rules do not decide; None if disabled


# ---------- Postgres context ----------

def make_context(conn: psycopg.Connection) -> Context:
    def _publish(type_, company, payload, correlation, causation):
        publish(conn, new_event(type_, company, payload, producer=PRODUCER, correlation_id=correlation,
                                causation_id=causation))

    def _company(company_id: str) -> dict:
        row = conn.execute("select to_jsonb(c) from companies c where id = %s", (company_id,)).fetchone()
        info = dict(row[0]) if row else {"id": company_id}
        info["as_of_date"] = str(info.get("as_of_date") or "") or None  # companies.tax_id: migration 007
        return info

    def _people(company_id: str) -> list[dict]:
        rows = conn.execute(
            """select p.id, p.name, p.email, p.role from people p where p.company_id = %s
               union all
               select p.id, p.name, a.address, p.role from person_addresses a join people p on p.id = a.person_id
               where p.company_id = %s""", (company_id, company_id)).fetchall()
        return [{"person_id": id_, "name": name, "email": email, "role": role}  # who-paid treats contractors as staff
                for id_, name, email, role in rows]

    def _raw_bytes(raw: dict) -> bytes | None:
        row = conn.execute("select bytes from raw_item_content where raw_item_id = %s", (raw["id"],)).fetchone()
        if row:
            return bytes(row[0])
        uri = raw.get("storage_uri") or ""
        if uri.startswith("pvc://raw/"):
            path = Path(os.environ.get("ORDO_RAW_DIR", "/data/raw")) / uri.removeprefix("pvc://raw/")
            if path.is_file():
                return path.read_bytes()
        return None

    return Context(store=Store(conn), publish=_publish, company=_company, people=_people, raw_bytes=_raw_bytes,
                   rates=default_rates(), choose=_CHOOSE)


# ---------- claiming ----------

def _handle(conn: psycopg.Connection, handlers: dict[str, Any], event: dict) -> None:
    ctx = make_context(conn)
    for handler in handlers.get(event["type"], []):
        handler(ctx, event)


def process_pending(conn: psycopg.Connection, consumer: str, retry_after_seconds: int = 30) -> int:
    """Handle every claimable delivery of one consumer group once. Returns how many succeeded."""
    handlers: dict[str, Any] = HANDLERS[consumer]
    return queue.process_pending(conn, consumer, lambda event: _handle(conn, handlers, event),
                                 retry_after_seconds=retry_after_seconds, max_attempts=MAX_ATTEMPTS,
                                 name=f"pipeline/{consumer}")


def sweep_all(conn: psycopg.Connection) -> None:
    """Missing documents and due-but-unpaid documents (#43), for every company."""
    try:
        ctx = make_context(conn)
        for (company,) in conn.execute("select id from companies").fetchall():
            counts = sweep(ctx, company)
            if any(counts.values()):
                log.info("pipeline: sweep %s %s", company, counts)
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("pipeline: sweep failed")


def rematch_all(conn: psycopg.Connection) -> None:
    """Once at start: re-pair every company's documents and bank lines with the current matcher (handlers.rematch)."""
    try:
        ctx = make_context(conn)
        for (company,) in conn.execute("select id from companies").fetchall():
            changed = rematch(ctx, company)
            if changed:
                log.info("pipeline: re-matched %s documents of %s", changed, company)
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("pipeline: re-match failed")


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = queue.listen(database_url())
        log.info("pipeline: listening (normaliser, matcher)")
        rematch_all(conn)
        last_sweep = 0.0
        while True:
            for consumer in ("normaliser", "matcher"):  # normaliser first: its output feeds the matcher
                process_pending(conn, consumer)
            if time.monotonic() - last_sweep >= SWEEP_SECONDS:
                sweep_all(conn)
                last_sweep = time.monotonic()
            queue.wait(listener, timeout=5.0)  # wake on NOTIFY, or poll every 5 s
