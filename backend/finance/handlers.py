"""Outbox handlers of the consumer group `finance`: book a decided Match, recompute the forecast after new inputs."""
import logging
import time
from typing import Any, Callable

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store

from .ledger import DECIDED, entries_for_match

log = logging.getLogger("ordo.finance")
PRODUCER = "finance"
DEBOUNCE_SECONDS = 2.0
DIRTY: dict[str, tuple[float, dict[str, Any]]] = {}


def on_inputs_changed(conn: psycopg.Connection, event: dict[str, Any]) -> None:
    if event.get("company_id"):
        DIRTY[event["company_id"]] = (time.monotonic(), event)


def recompute_due(conn: psycopg.Connection, *, debounce: float = DEBOUNCE_SECONDS, now: float | None = None) -> list[str]:
    from .engine import recompute

    now = time.monotonic() if now is None else now
    done = []
    for company, (seen, event) in list(DIRTY.items()):
        if now - seen < debounce:
            continue
        del DIRTY[company]
        try:
            recompute(conn, company, correlation_id=event.get("correlation_id"), causation_id=event["id"])
            done.append(company)
        except Exception:
            conn.rollback()
            log.exception("finance: recompute of %s failed", company)
    return done


def on_match_decided(conn: psycopg.Connection, event: dict[str, Any]) -> list[str]:
    s = Store(conn)
    payload = event["payload"]
    match = s.get("match", payload["match_id"])
    if match is None:
        log.warning("finance: %s refers to unknown match %s", event["id"], payload["match_id"])
        return []
    if payload.get("status") not in DECIDED or match.get("status") != payload.get("status"):
        return []
    company = event.get("company_id") or s.company_of("match", match["id"])
    document = s.get("document", match["document_id"])
    transaction = s.get("transaction", match["transaction_id"]) if match.get("transaction_id") else None
    entries = entries_for_match({**match, "company_id": company}, document and {"company_id": company, **document},
                                payload.get("approval_id"), transaction=transaction,
                                counterparties=s.list("counterparty", company_id=company))
    stored = []
    for entry in entries:
        existing = s.list("ledger_entry", match_id=match["id"], type=entry["type"])
        if existing and existing[0]["status"] != "proposed":
            continue
        if existing:
            entry = {**entry, "id": existing[0]["id"]}
            s.put("ledger_entry", entry, company_id=company)
        elif not s.add("ledger_entry", entry, company_id=company):
            continue
        stored.append(entry["id"])
        publish(conn, new_event("ledger.entry.approved", company,
                                {"ledger_entry_id": entry["id"], "approval_id": entry["approval_id"]},
                                producer=PRODUCER, correlation_id=event.get("correlation_id"),
                                causation_id=event["id"]))
    if stored:
        log.info("finance: %s booked %s", match["id"], ", ".join(stored))
    return stored


HANDLERS: dict[str, list[Callable[[psycopg.Connection, dict[str, Any]], Any]]] = {
    "match.decided": [on_match_decided],
    "transaction.ingested": [on_inputs_changed],
    "ledger.entry.approved": [on_inputs_changed],
    "execution.simulated": [on_inputs_changed],
    "document.extracted": [on_inputs_changed],
}
