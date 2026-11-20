"""`python -m backend connectors`: the connector process (role 2). Polls every source that has a connector here.

Each tick:
  1. runs the "sync now" requests (SyncRuns the API created with trigger `manual` and status `running`),
  2. runs every source whose `next_run_at` has passed (or that never ran).
At start it closes runs a previous process left `running` (the pod was killed mid-sync).

Options:
  --once            one tick, then exit (tests, manual runs)
  --reset-cursors   start the bank sources from the beginning: their stored cursors came from
                    contracts/fixtures (mock data) and would skip every real line
Environment: ORDO_DATABASE_URL, ORDO_BANK_URL, ORDO_BANK_TOKEN, ORDO_DEMO_MODE=1 (bank sources poll every 15 s).
"""
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
from backend.settings import database_url

log = logging.getLogger("ordo.connectors")
DEMO_INTERVAL_SECONDS = 15
TICK_SECONDS = 2.0


def build_connector(conn: psycopg.Connection, source: dict[str, Any], bank: httpx.Client) -> Connector | None:
    """The connector for a source, or None when role 2 has none for it (yet)."""
    if source["connector"] == "bank_psd2":
        return BankConnector(source, account_for_source(conn, source), bank)
    return None


def _sources(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("select doc from sources order by id").fetchall()
    conn.commit()
    return [r[0] for r in rows]


def _is_due(source: dict[str, Any], now: datetime) -> bool:
    if source.get("status") == "paused":
        return False
    nxt = source.get("next_run_at")
    if not nxt:
        return True
    return datetime.strptime(nxt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= now


def manual_requests(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """(source_id, run_id) of "sync now" requests not yet picked up."""
    rows = conn.execute(
        """select doc->>'source_id', id from sync_runs
           where doc->>'status' = 'running' and doc->>'trigger' = 'manual' and doc->>'finished_at' is null
           order by seq"""
    ).fetchall()
    conn.commit()
    return [(r[0], r[1]) for r in rows]


def recover_interrupted(conn: psycopg.Connection, now: datetime | None = None) -> int:
    """Close runs that are `running` although no process works on them (nobody holds the source's lock)."""
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
            continue  # a live process is running it
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
         sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """One pass over the sources. Returns the SyncRuns finished in it."""
    now = now or datetime.now(UTC)
    by_id = {s["id"]: s for s in _sources(conn)}
    done: list[dict[str, Any]] = []
    manual_sources = set()
    for source_id, run_id in manual_requests(conn):
        source = by_id.get(source_id)
        connector = build_connector(conn, source, bank) if source else None
        if connector is None:
            continue
        manual_sources.add(source_id)
        result = run_once(conn, connector, trigger="manual", run_id=run_id, sleep=sleep)
        if result:
            done.append(result)
    for source in by_id.values():
        if source["id"] in manual_sources or not _is_due(source, now):
            continue
        connector = build_connector(conn, source, bank)
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

    with psycopg.connect(database_url()) as conn, make_client() as bank:
        if args.reset_cursors:
            log.info("reset the cursors of %d bank sources", reset_bank_cursors(conn))
        if os.environ.get("ORDO_DEMO_MODE") == "1":
            apply_demo_intervals(conn)
        closed = recover_interrupted(conn)
        if closed:
            log.info("closed %d runs left running by a previous process", closed)
        first = True
        while True:
            tick(conn, bank, first=first)
            first = False
            if args.once:
                return 0
            time.sleep(TICK_SECONDS)
