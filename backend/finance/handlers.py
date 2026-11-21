"""Outbox handlers of the consumer group `finance` (contracts/events.md).

    match.decided          book the Ledger entries of a confirmed (or auto-confirmed) purchase Match, emit
                           ledger.entry.approved (#27)
    transaction.ingested   mark the company: its forecast is recomputed 2 s after the last such event (#28)
    ledger.entry.approved  same
    execution.simulated    same
    approval.recorded      -- nothing

Every handler can run twice: entries have ids derived from the Match and `Store.add` ignores a repeated id,
and `ledger.entry.approved` is emitted only for entries stored now.
"""
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
# company id -> (time of its last input event, that event); emptied by recompute_due()
DIRTY: dict[str, tuple[float, dict[str, Any]]] = {}


def on_inputs_changed(conn: psycopg.Connection, event: dict[str, Any]) -> None:
    """A new bank line, an approved Ledger entry or an executed action: the forecast must be recomputed."""
    if event.get("company_id"):
        DIRTY[event["company_id"]] = (time.monotonic(), event)


def recompute_due(conn: psycopg.Connection, *, debounce: float = DEBOUNCE_SECONDS, now: float | None = None) -> list[str]:
    """Recompute the forecast of every company whose last input event is at least `debounce` seconds old."""
    from .engine import recompute  # late import: the engine reads many tables, the handlers only a few

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
    """Book what a decided Match calls for. Returns the ids of the entries stored by this call."""
    s = Store(conn)
    payload = event["payload"]
    match = s.get("match", payload["match_id"])
    if match is None:
        log.warning("finance: %s refers to unknown match %s", event["id"], payload["match_id"])
        return []
    if payload.get("status") not in DECIDED or match.get("status") != payload.get("status"):
        return []  # rejected (or decided differently since): nothing is booked
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
            continue  # already booked (or voided): the same decision twice books once
        if existing:  # a proposed entry (e.g. the contract fixture) becomes the approved one, keeping its id
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
}
