"""`python -m backend pipeline`: the pipeline process (role 3). Serves the outbox consumer groups `normaliser` and
`matcher` (backend/pipeline/handlers.py says which events do what).

Claiming follows contracts/events.md and role 5's agent loop (SKIP LOCKED, done after commit, 3 failures -> dead).
When role 2's backend/queue library lands, this loop switches to it.

Environment: ORDO_DATABASE_URL (backend/settings.py); ORDO_RAW_DIR = where pvc://raw/ is mounted (default /data/raw).
"""
import logging
import os
from pathlib import Path
from typing import Any

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store
from backend.settings import database_url

from .handlers import COMPANY_TAX_IDS, HANDLERS, PRODUCER, Context, default_rates

log = logging.getLogger("ordo.pipeline")
MAX_ATTEMPTS = 3


# ---------- Postgres context ----------

def make_context(conn: psycopg.Connection) -> Context:
    def _publish(type_, company, payload, correlation, causation):
        publish(conn, new_event(type_, company, payload, producer=PRODUCER, correlation_id=correlation,
                                causation_id=causation))

    def _company(company_id: str) -> dict:
        row = conn.execute("select to_jsonb(c) from companies c where id = %s", (company_id,)).fetchone()
        info = dict(row[0]) if row else {"id": company_id}
        info["as_of_date"] = str(info.get("as_of_date") or "") or None
        info["tax_id"] = info.get("tax_id") or COMPANY_TAX_IDS.get(company_id)
        return info

    def _people(company_id: str) -> list[dict]:
        rows = conn.execute(
            """select p.id, p.name, p.email, p.role from people p where p.company_id = %s
               union all
               select p.id, p.name, a.address, p.role from person_addresses a join people p on p.id = a.person_id
               where p.company_id = %s""", (company_id, company_id)).fetchall()
        return [{"person_id": id_, "name": name, "email": email, "role": role if role != "contractor" else "unknown"}
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
                   rates=default_rates())


# ---------- claiming ----------

def _claim(conn: psycopg.Connection, consumer: str, retry_after_seconds: int):
    row = conn.execute(
        """select d.event_id, d.attempts, o.type, o.company_id, o.occurred_at, o.correlation_id, o.payload
           from outbox_delivery d join outbox o on o.id = d.event_id
           where d.consumer = %s and d.status = 'pending' and (d.locked_until is null or d.locked_until < now())
           order by o.seq limit 1 for update of d skip locked""",
        (consumer,),
    ).fetchone()
    if row is None:
        return None
    event_id, attempts, type_, company, occurred_at, correlation, payload = row
    conn.execute(
        "update outbox_delivery set attempts = attempts + 1, locked_until = now() + make_interval(secs => %s) "
        "where event_id = %s and consumer = %s", (max(retry_after_seconds, 0), event_id, consumer))
    event = {"id": event_id, "type": type_, "company_id": company, "correlation_id": correlation, "payload": payload,
             "occurred_at": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return event, attempts + 1


def process_pending(conn: psycopg.Connection, consumer: str, retry_after_seconds: int = 30) -> int:
    """Handle every claimable delivery of one consumer group once. Returns how many succeeded."""
    handlers: dict[str, Any] = HANDLERS[consumer]
    handled = 0
    while True:
        claimed = _claim(conn, consumer, retry_after_seconds)
        if claimed is None:
            conn.commit()
            return handled
        event, attempt = claimed
        conn.commit()
        try:
            ctx = make_context(conn)
            for handler in handlers.get(event["type"], []):
                handler(ctx, event)
            conn.execute("update outbox_delivery set status = 'done', locked_until = null "
                         "where event_id = %s and consumer = %s", (event["id"], consumer))
            conn.commit()
            handled += 1
        except Exception:
            conn.rollback()
            log.exception("pipeline/%s: %s %s failed (attempt %d)", consumer, event["type"], event["id"], attempt)
            if attempt >= MAX_ATTEMPTS:
                conn.execute("update outbox_delivery set status = 'dead' where event_id = %s and consumer = %s",
                             (event["id"], consumer))
                conn.commit()


def run(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    with psycopg.connect(database_url(), autocommit=False) as conn:
        listener = psycopg.connect(database_url(), autocommit=True)
        listener.execute("listen outbox")
        log.info("pipeline: listening (normaliser, matcher)")
        while True:
            for consumer in ("normaliser", "matcher"):  # normaliser first: its output feeds the matcher
                process_pending(conn, consumer)
            for _ in listener.notifies(timeout=5.0, stop_after=1):  # wake on NOTIFY, or poll every 5 s
                pass
