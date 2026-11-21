"""`python -m backend connectors [--once] [--reset-cursors]`: runs "sync now" requests and every source that is due."""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Jsonb

from backend.connectors.bank import BankConnector, account_for_source, make_client
from backend.connectors.base import Connector, iso, run_once
from backend.connectors.mailbox import ImapConnector, imap_configured, imap_settings
from backend.connectors.nbp import NbpConnector, make_nbp_client
from backend.settings import database_url

log = logging.getLogger("ordo.connectors")
DEMO_INTERVAL_SECONDS = 15
TICK_SECONDS = 2.0


def enabled_connectors() -> set[str] | None:
    raw = os.environ.get("ORDO_CONNECTORS_ONLY", "").strip()
    return {c.strip() for c in raw.split(",") if c.strip()} or None


def show_mailbox_address(conn: psycopg.Connection, source: dict[str, Any], address: str) -> dict[str, Any]:
    """The invoices mailbox's address on its Source, from the Secret-backed ORDO_IMAP_USER, never from Git."""
    public = dict(source.get("config_public") or {})
    if public.get("mailbox") == address:
        return source
    source = {**source, "config_public": {**public, "mailbox": address}}
    conn.execute("update sources set doc = %s where id = %s", (Jsonb(source), source["id"]))
    conn.commit()
    return source


def build_connector(conn: psycopg.Connection, source: dict[str, Any], bank: httpx.Client,
                    nbp: httpx.Client | None = None) -> Connector | None:
    only = enabled_connectors()
    if only is not None and source["connector"] not in only:
        return None
    if source["connector"] == "bank_psd2":
        return BankConnector(source, account_for_source(conn, source), bank)
    if source["connector"] == "fx_rates" and nbp is not None:
        return NbpConnector(source, nbp)
    if source["connector"] == "imap_mailbox" and imap_configured():
        return ImapConnector(show_mailbox_address(conn, source, imap_settings()["user"].lower()))
    return None


def _sources(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("select doc from sources order by id").fetchall()
    conn.commit()
    return [r[0] for r in rows]


def _is_due(source: dict[str, Any], now: datetime, first: bool = False) -> bool:
    if source.get("status") == "paused":
        return False
    nxt = source.get("next_run_at")
    if first or not nxt:
        return True
    try:
        at = datetime.strptime(nxt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return True
    interval = int(source.get("poll_interval_seconds") or 60)
    return at <= now or (at - now).total_seconds() > 2 * interval


def manual_requests(conn: psycopg.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        """select doc->>'source_id', id from sync_runs
           where doc->>'status' = 'running' and doc->>'trigger' = 'manual' and doc->>'finished_at' is null
           order by seq"""
    ).fetchall()
    conn.commit()
    return [(r[0], r[1]) for r in rows]


def recover_interrupted(conn: psycopg.Connection, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = conn.execute(
        "select id, doc from sync_runs where doc->>'status' = 'running' and doc->>'trigger' <> 'manual'"
    ).fetchall()
    conn.commit()
    closed = 0
    for run_id, doc in rows:
        key = f"connector:{doc['source_id']}"
        if not conn.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()[0]:
            conn.commit()
            continue
        try:
            doc.update(status="failed", finished_at=iso(now), error={
                "code": "interrupted", "message": "the connector process stopped during this run", "retryable": True})
            conn.execute("update sync_runs set doc = %s where id = %s", (Jsonb(doc), run_id))
            conn.execute(
                """update sources set doc = doc || '{"status": "degraded"}'::jsonb
                   where id = %s and doc->>'status' = 'syncing'""", (doc["source_id"],))
            conn.commit()
            closed += 1
        finally:
            conn.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
            conn.commit()
    return closed


def reset_bank_cursors(conn: psycopg.Connection) -> int:
    cur = conn.execute(
        """update sources set doc = doc || '{"cursor": null, "items_total": 0, "next_run_at": null}'::jsonb
           where doc->>'connector' = 'bank_psd2'"""
    )
    conn.commit()
    return cur.rowcount


def apply_demo_intervals(conn: psycopg.Connection) -> None:
    conn.execute(
        """update sources set doc = jsonb_set(doc, '{poll_interval_seconds}', to_jsonb(%s::int))
           where doc->>'connector' = 'bank_psd2'""", (DEMO_INTERVAL_SECONDS,))
    conn.commit()


def tick(conn: psycopg.Connection, bank: httpx.Client, *, now: datetime | None = None, first: bool = False,
         sleep: Callable[[float], None] = time.sleep, nbp: httpx.Client | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    by_id = {s["id"]: s for s in _sources(conn)}
    done: list[dict[str, Any]] = []
    manual_sources = set()
    for source_id, run_id in manual_requests(conn):
        source = by_id.get(source_id)
        connector = build_connector(conn, source, bank, nbp) if source else None
        if connector is None:
            continue
        manual_sources.add(source_id)
        result = run_once(conn, connector, trigger="manual", run_id=run_id, sleep=sleep)
        if result:
            done.append(result)
    for source in by_id.values():
        if source["id"] in manual_sources or not _is_due(source, now, first):
            continue
        connector = build_connector(conn, source, bank, nbp)
        if connector is None:
            continue
        result = run_once(conn, connector, trigger="startup" if first else "schedule", sleep=sleep)
        if result:
            done.append(result)
            log.info("%s: %s, %d new", source["id"], result["status"], result["items_new"])
    return done


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend connectors")
    parser.add_argument("--once", action="store_true", help="one tick, then exit")
    parser.add_argument("--reset-cursors", action="store_true", help="start bank sources from the beginning")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    with psycopg.connect(database_url()) as conn, make_client() as bank, make_nbp_client() as nbp:
        if args.reset_cursors:
            log.info("reset the cursors of %d bank sources", reset_bank_cursors(conn))
        if os.environ.get("ORDO_DEMO_MODE") == "1":
            apply_demo_intervals(conn)
        closed = recover_interrupted(conn)
        if closed:
            log.info("closed %d runs left running by a previous process", closed)
        first = True
        while True:
            tick(conn, bank, first=first, nbp=nbp)
            first = False
            if args.once:
                return 0
            time.sleep(TICK_SECONDS)
