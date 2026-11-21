"""The connector base against the real tables."""
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

import backend.connectors.base as base
from backend.connectors.base import (AuthError, Connector, ConnectorError, FetchedItem, FetchResult,
                                     idempotency_key, run_once)
from backend.db.contracts import MODELS
from backend.db.store import Store

SOURCE = {
    "id": "src_test_bank", "company_id": "co_borsuk", "connector": "bank_psd2", "display_name": "Test bank (SAMPLE)",
    "status": "connected", "mode": "polling", "poll_interval_seconds": 60, "cursor": None, "items_total": 0,
    "config_public": {"account_id": "acc_pln"}, "is_sandbox": True,
}


class FakeBank(Connector):
    """Serves `pages` in order; an entry that is an exception is raised instead of returned."""

    connector = "bank_psd2"
    key_prefix = "bank"

    def __init__(self, source, pages):
        super().__init__(source)
        self.pages = list(pages)
        self.cursors_asked: list[str | None] = []

    def key_scope(self):
        return self.source["config_public"]["account_id"]

    def fetch(self, cursor):
        self.cursors_asked.append(cursor)
        nxt = self.pages.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def line(ref: str, amount: str = "-10.00") -> FetchedItem:
    return FetchedItem(kind="bank_transaction", external_id=ref,
                       payload={"entryReference": ref, "transactionAmount": {"amount": amount, "currency": "PLN"}})


def page(*refs: str, more: bool = False) -> FetchResult:
    return FetchResult(items=[line(r) for r in refs], cursor=refs[-1] if refs else None, more=more)


@pytest.fixture
def source(db):
    db.execute("insert into sources (id, company_id, doc) values (%s, %s, %s)",
               (SOURCE["id"], SOURCE["company_id"], Jsonb(SOURCE)))
    db.commit()
    return dict(SOURCE)


def run(db, connector, waited=None, **kw):
    sleeps = waited if waited is not None else []
    return run_once(db, connector, sleep=sleeps.append, **kw)


def stored_source(db) -> dict:
    return Store(db).get("source", SOURCE["id"])


def events(db, type_: str) -> list[dict]:
    rows = db.execute("select payload, correlation_id, company_id from outbox where type = %s order by seq", (type_,))
    return [{"payload": p, "correlation_id": c, "company_id": co} for p, c, co in rows.fetchall()]


def raw_items(db) -> list[dict]:
    return Store(db).list("raw_item", source_id=SOURCE["id"])


def test_second_run_creates_no_new_raw_items(db, source):
    first = run(db, FakeBank(source, [page("E000000001", "E000000002")]))
    assert first["status"] == "success" and first["items_new"] == 2

    # the source "forgets" the cursor and serves the same lines again: the unique key must stop them
    db.execute("update sources set doc = jsonb_set(doc, '{cursor}', 'null') where id = %s", (SOURCE["id"],))
    db.commit()
    second = run(db, FakeBank(source, [page("E000000001", "E000000002")]))
    assert second["status"] == "success"
    assert (second["items_fetched"], second["items_new"], second["items_duplicate"]) == (2, 0, 2)
    assert len(raw_items(db)) == 2
    assert len(events(db, "raw_item.received")) == 2  # no event for a duplicate


def test_items_cursor_and_events_are_written(db, source):
    bank = FakeBank(source, [page("E000000001", "E000000002")])
    result = run(db, bank)
    assert bank.cursors_asked == [None]
    src = stored_source(db)
    assert src["cursor"] == "E000000002" and src["items_total"] == 2
    assert result["cursor_before"] is None and result["cursor_after"] == "E000000002"

    item = Store(db).get("raw_item", raw_items(db)[0]["id"])
    assert item["kind"] == "bank_transaction" and item["processing_status"] == "queued"
    assert item["sync_run_id"] == result["id"]
    received = events(db, "raw_item.received")
    assert received[0]["company_id"] == "co_borsuk"
    assert {e["payload"]["raw_item_id"] for e in received} == {i["id"] for i in raw_items(db)}
    assert all(e["correlation_id"] == e["payload"]["raw_item_id"] for e in received)  # events.md rule 2

    # the next run starts from the stored cursor
    bank2 = FakeBank(source, [page()])
    run(db, bank2)
    assert bank2.cursors_asked == ["E000000002"]


def test_idempotency_key_follows_the_spec():
    expected = hashlib.sha256(b"bank:acc_pln:E000000731").hexdigest()
    assert idempotency_key("bank", "acc_pln", "E000000731") == expected
    with_file = hashlib.sha256(b"imap:inbox:<m1>:" + b"ab" * 32).hexdigest()
    assert idempotency_key("imap", "inbox", "<m1>", "ab" * 32) == with_file


def test_pages_are_followed_and_each_page_is_committed(db, source):
    result = run(db, FakeBank(source, [page("E000000001", more=True), page("E000000002", more=True), page("E000000003")]))
    assert result["status"] == "success" and result["items_new"] == 3
    assert stored_source(db)["cursor"] == "E000000003"


def test_documents_are_valid_against_the_contract(db, source):
    result = run(db, FakeBank(source, [page("E000000001")]))
    MODELS["sync_run"].model_validate(result)
    MODELS["sync_run"].model_validate(Store(db).get("sync_run", result["id"]))
    MODELS["source"].model_validate(stored_source(db))
    for item in raw_items(db):
        MODELS["raw_item"].model_validate(item)


def test_source_status_and_times_on_success(db, source):
    t0 = datetime(2026, 11, 21, 10, 14, 0, tzinfo=UTC)
    times = iter([t0, t0 + timedelta(seconds=2)])
    result = run(db, FakeBank(source, [page("E000000001")]), clock=lambda: next(times))
    src = stored_source(db)
    assert src["status"] == "connected" and src["last_error"] is None
    assert src["last_success_at"] == src["last_synced_at"] == "2026-11-21T10:14:02Z"
    assert src["next_run_at"] == "2026-11-21T10:15:02Z"  # + poll_interval_seconds
    assert result["started_at"] == "2026-11-21T10:14:00Z" and result["duration_ms"] == 2000
    started = events(db, "sync.run.started")
    finished = events(db, "sync.run.finished")
    assert started[0]["payload"] == {"sync_run_id": result["id"], "source_id": SOURCE["id"]}
    assert finished[0]["payload"] == {"sync_run_id": result["id"], "source_id": SOURCE["id"],
                                      "status": "success", "items_new": 1}


def test_retries_three_times_then_degraded(db, source):
    waited: list[float] = []
    down = [ConnectorError("bank timed out")] * 4
    result = run(db, FakeBank(source, down), waited)
    assert waited == [5, 20, 60]
    assert result["status"] == "failed" and result["attempt"] == 4
    assert result["error"] == {"code": "fetch_failed", "message": "bank timed out", "retryable": True}
    src = stored_source(db)
    assert src["status"] == "degraded" and src["last_error"]["message"] == "bank timed out"
    assert src.get("last_success_at") is None  # never succeeded
    assert events(db, "sync.run.finished")[0]["payload"]["status"] == "failed"
    assert events(db, "sync.run.finished")[0]["payload"]["error"] == "bank timed out"


def test_a_retry_that_works_is_a_success(db, source):
    waited: list[float] = []
    result = run(db, FakeBank(source, [ConnectorError("blip"), page("E000000001")]), waited)
    assert waited == [5]
    assert result["status"] == "success" and result["attempt"] == 2 and result["items_new"] == 1
    assert stored_source(db)["status"] == "connected"


def test_untyped_exceptions_are_retried_too(db, source):
    waited: list[float] = []
    result = run(db, FakeBank(source, [TimeoutError("socket"), page("E000000001")]), waited)
    assert waited == [5] and result["status"] == "success"


def test_auth_error_is_not_retried_and_sets_error(db, source):
    waited: list[float] = []
    result = run(db, FakeBank(source, [AuthError("token rejected")]), waited)
    assert waited == []
    assert result["status"] == "failed" and result["error"]["code"] == "auth_failed"
    assert result["error"]["retryable"] is False
    assert stored_source(db)["status"] == "error"


def test_failure_after_a_committed_page_is_partial_and_resumes(db, source):
    down = [ConnectorError("gone")] * 4
    result = run(db, FakeBank(source, [page("E000000001", more=True), *down]))
    assert result["status"] == "partial" and result["items_new"] == 1
    assert stored_source(db)["cursor"] == "E000000001"  # what was committed stays
    bank = FakeBank(source, [page("E000000002")])
    run(db, bank)
    assert bank.cursors_asked == ["E000000001"]
    assert len(raw_items(db)) == 2


def test_a_page_is_all_or_nothing(db, source, monkeypatch):
    """Items, their events and the cursor share one transaction: if the event cannot be written, nothing is."""
    real_publish = base.publish

    def failing_publish(conn, event, commit=True):
        if event["type"] == "raw_item.received":
            raise RuntimeError("outbox down")
        return real_publish(conn, event, commit=commit)

    monkeypatch.setattr(base, "publish", failing_publish)
    result = run(db, FakeBank(source, [page("E000000001", "E000000002")]))
    assert result["status"] == "failed" and result["error"]["code"] == "store_failed"
    assert raw_items(db) == []
    assert stored_source(db)["cursor"] is None and stored_source(db)["items_total"] == 0
    assert Store(db).get("sync_run", result["id"])["status"] == "failed"  # not left "running"


def test_adopts_the_run_created_by_the_sync_now_button(db, source):
    manual = {"id": "run_manual01", "source_id": SOURCE["id"], "connector": "bank_psd2", "trigger": "manual",
              "started_at": "2026-11-21T10:00:00Z", "status": "running"}
    Store(db).add("sync_run", manual, company_id="co_borsuk")
    result = run(db, FakeBank(source, [page("E000000001")]), trigger="manual", run_id="run_manual01")
    assert result["id"] == "run_manual01" and result["trigger"] == "manual"
    assert Store(db).get("sync_run", "run_manual01")["status"] == "success"
    assert len(Store(db).list("sync_run", source_id=SOURCE["id"])) == 1


def test_a_second_concurrent_run_of_the_same_source_is_skipped(db, db_url, source):
    import psycopg

    with psycopg.connect(db_url) as other:
        other.execute("select pg_advisory_lock(hashtext(%s))", (f"connector:{SOURCE['id']}",))
        assert run(db, FakeBank(source, [page("E000000001")])) is None
        other.execute("select pg_advisory_unlock(hashtext(%s))", (f"connector:{SOURCE['id']}",))
    assert run(db, FakeBank(source, [page("E000000001")]))["status"] == "success"


def test_unknown_source_is_an_error(db):
    with pytest.raises(LookupError):
        run(db, FakeBank({**SOURCE, "id": "src_missing"}, []))
