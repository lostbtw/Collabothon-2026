"""The connector base every source uses (bank, mailbox, NBP rates). Owner: role 2.

A connector only says how to ask its source for news:

    class BankConnector(Connector):
        connector = "bank_psd2"          # contracts/schemas/common.schema.json#/$defs/Connector
        key_prefix = "bank"              # first part of the idempotency key

        def key_scope(self) -> str:      # account / mailbox the external ids are unique in
            return self.source["config_public"]["account_id"]

        def fetch(self, cursor):         # everything after the cursor, one page
            ...
            return FetchResult(items=[FetchedItem(kind="bank_transaction", external_id=ref, payload=line)],
                               cursor=last_ref, more=has_next_page)

`run_once(conn, connector)` does the rest, as contracts/events.md and the role 2 spec require:
open a SyncRun, fetch page by page from the stored cursor, key every item, insert it once (the unique index on
raw_items.idempotency_key turns a repeat into a counted duplicate), emit `raw_item.received`, and advance the
cursor in the SAME transaction as the items of that page. A failing fetch is retried 3 times (5 s, 20 s, 60 s);
when that is exhausted the source is `degraded`, an authentication error makes it `error` at once.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from backend.db.events import new_event, publish

RETRY_DELAYS = (5, 20, 60)  # seconds before retry 1, 2, 3
MAX_MESSAGE = 500


# ---------- what a connector returns ----------
@dataclass
class FetchedItem:
    kind: str  # raw_item.kind: bank_transaction, email, email_attachment, fx_rate_table, ...
    external_id: str  # id in the source system: entryReference, Message-ID, NBP table number
    payload: dict[str, Any] | None = None  # small structured items (bank line, rate table)
    metadata: dict[str, Any] = field(default_factory=dict)
    received_at: str | None = None
    content_type: str | None = None
    sha256: str | None = None  # files: content hash, also part of the idempotency key
    size_bytes: int | None = None
    storage_uri: str | None = None
    parent_external_id: str | None = None  # attachment -> its e-mail, in the same fetch


@dataclass
class FetchResult:
    items: list[FetchedItem]
    cursor: str | None  # cursor after these items; stored only once they are committed
    more: bool = False  # another page is waiting: fetch again from `cursor` in the same run


class ConnectorError(Exception):
    """A failed fetch. `retryable` decides between a retry (then `degraded`) and `error` at once."""

    code = "fetch_failed"
    retryable = True

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None):
        super().__init__(message)
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class AuthError(ConnectorError):
    """Wrong token, password or consent: retrying cannot help."""

    code = "auth_failed"
    retryable = False


class Connector(ABC):
    connector: str  # Connector enum value of the contract
    key_prefix: str  # first part of the idempotency key: bank, imap, nbp, ...

    def __init__(self, source: dict[str, Any]):
        self.source = source

    def key_scope(self) -> str:
        """What external ids are unique within (account, mailbox). Defaults to the source."""
        return self.source["id"]

    def cursor_external_id(self, cursor: str | None) -> str | None:
        """The external id of the item the cursor points at, if the cursor names one (bank: the entryReference).
        A cursor whose item is not in our database is not ours (contracts/fixtures, another bank): the run then
        starts from the beginning. None = this connector cannot tell, the cursor is trusted."""
        return None

    @abstractmethod
    def fetch(self, cursor: str | None) -> FetchResult:
        """Everything after `cursor` (None = from the beginning), at most one page. Raise ConnectorError on failure."""


# ---------- helpers ----------
def idempotency_key(prefix: str, scope: str, external_id: str, content_sha256: str | None = None) -> str:
    """sha256 of `<prefix>:<scope>:<external_id>` (plus `:<content sha256>` for files), as in the role 2 spec."""
    text = f"{prefix}:{scope}:{external_id}" + (f":{content_sha256}" if content_sha256 else "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_item_id(key: str) -> str:
    """Deterministic: the same item always gets the same id."""
    return f"raw_{key[:20]}"


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_info(exc: BaseException) -> dict[str, Any]:
    code = getattr(exc, "code", None) or "fetch_failed"
    retryable = getattr(exc, "retryable", True)
    message = str(exc) or exc.__class__.__name__
    return {"code": code, "message": message[:MAX_MESSAGE], "retryable": bool(retryable)}


def _put(conn: psycopg.Connection, table: str, doc: dict[str, Any], company_id: str | None) -> None:
    """Insert or replace by id, without committing (the caller owns the transaction)."""
    conn.execute(
        f"""insert into {table} (id, company_id, doc) values (%s, %s, %s)
            on conflict (id) do update set doc = excluded.doc""",
        (doc["id"], company_id, Jsonb(doc)),
    )


def _load_source(conn: psycopg.Connection, source_id: str) -> dict[str, Any]:
    row = conn.execute("select doc from sources where id = %s", (source_id,)).fetchone()
    if row is None:
        raise LookupError(f"source {source_id} does not exist")
    return row[0]


# ---------- the run ----------
def run_once(
    conn: psycopg.Connection,
    connector: Connector,
    *,
    trigger: str = "schedule",
    run_id: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any] | None:
    """One sync of one source. Returns the finished SyncRun, or None when another run of it is in progress.

    `run_id` adopts an existing running SyncRun (the API's "sync now" button creates one with trigger `manual`).
    `sleep` and `clock` are injectable so tests do not wait for the retry delays.
    """
    source_id = connector.source["id"]
    # one run per source at a time, across processes
    locked = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (f"connector:{source_id}",)).fetchone()[0]
    conn.commit()
    if not locked:
        return None
    try:
        return _run(conn, connector, trigger=trigger, run_id=run_id, sleep=sleep, clock=clock)
    finally:
        conn.rollback()  # leave no half-open transaction behind before unlocking
        conn.execute("select pg_advisory_unlock(hashtext(%s))", (f"connector:{source_id}",))
        conn.commit()


def _run(conn, connector, *, trigger, run_id, sleep, clock) -> dict[str, Any]:
    source = _load_source(conn, connector.source["id"])
    connector.source = source
    cursor_before = source.get("cursor")
    pointed = connector.cursor_external_id(cursor_before)
    if pointed is not None:
        key = idempotency_key(connector.key_prefix, connector.key_scope(), pointed)
        if conn.execute("select 1 from raw_items where idempotency_key = %s", (key,)).fetchone() is None:
            source["cursor"] = None  # not a cursor we wrote: read from the beginning, duplicates are skipped
    conn.commit()  # end the reads so each `with conn.transaction()` below is a real, separately committed transaction
    company = source["company_id"]
    started = clock()
    run: dict[str, Any] = {
        "id": run_id or f"run_{uuid.uuid4().hex[:10]}",
        "source_id": source["id"],
        "connector": source["connector"],
        "trigger": trigger,
        "started_at": iso(started),
        "finished_at": None,
        "status": "running",
        "cursor_before": cursor_before,
        "cursor_after": source.get("cursor"),
        "items_fetched": 0,
        "items_new": 0,
        "items_duplicate": 0,
        "error": None,
        "attempt": 1,
        "duration_ms": None,
    }
    with conn.transaction():
        _put(conn, "sync_runs", run, company)
        source["status"] = "syncing"
        _put(conn, "sources", source, company)
        publish(conn, new_event("sync.run.started", company, {"sync_run_id": run["id"], "source_id": source["id"]},
                                producer="connector"), commit=False)

    cursor = source.get("cursor")
    pages_committed = 0
    error: BaseException | None = None
    retries_left = list(RETRY_DELAYS)
    while True:
        try:
            result = connector.fetch(cursor)
        except Exception as exc:  # noqa: BLE001 - any failure of the source counts, typed or not
            if getattr(exc, "retryable", True) and retries_left:
                sleep(retries_left.pop(0))
                run["attempt"] += 1
                continue
            error = exc
            break
        before = (dict(source), dict(run))
        try:
            _commit_page(conn, connector, source, run, result)
        except Exception as exc:  # noqa: BLE001 - the page was rolled back; end the run as failed, not "running"
            source.clear(); source.update(before[0])
            run.clear(); run.update(before[1])
            error = ConnectorError(f"could not store the fetched items: {exc}", code="store_failed", retryable=True)
            break
        cursor = source.get("cursor")
        pages_committed += 1
        if not result.more:
            break

    finished = clock()
    run["finished_at"] = iso(finished)
    run["duration_ms"] = int((finished - started).total_seconds() * 1000)
    run["cursor_after"] = source.get("cursor")
    source["last_synced_at"] = iso(finished)
    if error is None:
        run["status"] = "success"
        source.update(status="connected", last_success_at=iso(finished), last_error=None)
    else:
        info = _error_info(error)
        run["error"] = info
        run["status"] = "partial" if pages_committed else "failed"
        source.update(status="degraded" if info["retryable"] else "error", last_error=info)
    interval = int(source.get("poll_interval_seconds") or 60)
    source["next_run_at"] = iso(finished + timedelta(seconds=interval))

    payload = {"sync_run_id": run["id"], "source_id": source["id"], "status": run["status"], "items_new": run["items_new"]}
    if run["error"]:
        payload["error"] = run["error"]["message"]
    with conn.transaction():
        _put(conn, "sync_runs", run, company)
        _put(conn, "sources", source, company)
        publish(conn, new_event("sync.run.finished", company, payload, producer="connector"), commit=False)
    return run


def _commit_page(conn: psycopg.Connection, connector: Connector, source: dict[str, Any], run: dict[str, Any],
                 result: FetchResult) -> None:
    """Items of one page, their events and the new cursor: all or nothing."""
    scope = connector.key_scope()
    company = source["company_id"]
    now = iso(datetime.now(UTC))
    new = dup = 0
    ids_by_external: dict[str, str] = {}
    with conn.transaction():
        for item in result.items:
            key = idempotency_key(connector.key_prefix, scope, item.external_id, item.sha256)
            rid = raw_item_id(key)
            ids_by_external[item.external_id] = rid
            doc = {
                "id": rid,
                "source_id": source["id"],
                "sync_run_id": run["id"],
                "kind": item.kind,
                "external_id": item.external_id,
                "idempotency_key": key,
                "parent_raw_item_id": ids_by_external.get(item.parent_external_id) if item.parent_external_id else None,
                "received_at": item.received_at,
                "fetched_at": now,
                "content_type": item.content_type,
                "storage_uri": item.storage_uri,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "metadata": item.metadata,
                "payload": item.payload,
                "processing_status": "queued",
                "error": None,
            }
            stored = conn.execute(
                "insert into raw_items (id, company_id, doc) values (%s, %s, %s) on conflict do nothing",
                (rid, company, Jsonb(doc)),
            ).rowcount == 1
            if stored:
                new += 1
                publish(conn, new_event("raw_item.received", company,
                                        {"raw_item_id": rid, "kind": item.kind, "source_id": source["id"]},
                                        producer="connector", correlation_id=rid), commit=False)
            else:
                dup += 1
        if result.cursor is not None:
            source["cursor"] = result.cursor
        # counted, not added up: stays right whatever happened to the cursor (fixtures, a reset, a re-read)
        source["items_total"] = conn.execute("select count(*) from raw_items where source_id = %s",
                                             (source["id"],)).fetchone()[0]
        run["items_fetched"] += len(result.items)
        run["items_new"] += new
        run["items_duplicate"] += dup
        run["cursor_after"] = source.get("cursor")
        _put(conn, "sources", source, company)
        _put(conn, "sync_runs", run, company)
