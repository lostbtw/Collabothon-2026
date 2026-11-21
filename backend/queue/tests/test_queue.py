"""The outbox consumer library against the real tables."""
import threading
import time

import psycopg
from psycopg.types.json import Jsonb

from backend import queue
from backend.db.events import new_event, publish


def delivery(db, event_id, consumer):
    return db.execute("select status, attempts from outbox_delivery where event_id = %s and consumer = %s",
                      (event_id, consumer)).fetchone()


def emit(db, type_="transaction.ingested", **payload):
    event = new_event(type_, "co_borsuk", payload or {"transaction_id": "txn_x"}, producer="test")
    publish(db, event)
    return event


def test_a_delivery_is_handled_once_and_marked_done(db):
    event = emit(db)
    seen = []
    assert queue.process_pending(db, "finance", seen.append) == 1
    assert [e["id"] for e in seen] == [event["id"]] and seen[0]["occurred_at"].endswith("Z")
    assert delivery(db, event["id"], "finance") == ("done", 1)
    assert queue.process_pending(db, "finance", seen.append) == 0
    assert delivery(db, event["id"], "matcher") == ("pending", 0)  # every consumer group has its own delivery


def test_two_workers_never_take_the_same_delivery(db, db_url):
    first, second = emit(db), emit(db)
    with psycopg.connect(db_url) as other:
        mine = queue.claim(db, "finance")  # holds the row lock: not committed yet
        theirs = queue.claim(other, "finance")
        assert {mine[0]["id"], theirs[0]["id"]} == {first["id"], second["id"]}
        assert queue.claim(other, "finance") is None  # nothing else is free
        other.rollback()
    db.rollback()


def test_a_claimed_delivery_waits_for_its_retry_time(db):
    emit(db)
    queue.claim(db, "finance", retry_after_seconds=60)
    db.commit()  # the worker died after claiming
    assert queue.claim(db, "finance") is None  # locked until the retry time
    db.rollback()


def test_a_handler_failing_three_times_ends_dead_and_its_raw_item_failed(db):
    raw = {"id": "raw_q1", "source_id": "src_mail", "sync_run_id": "run_q", "kind": "email_attachment",
           "external_id": "<m>#1", "idempotency_key": "kq1", "fetched_at": "2026-11-21T10:00:00Z",
           "metadata": {}, "processing_status": "queued"}
    db.execute("insert into raw_items (id, company_id, doc) values (%s, %s, %s)", ("raw_q1", "co_borsuk", Jsonb(raw)))
    db.commit()
    event = emit(db, "raw_item.received", raw_item_id="raw_q1", kind="email_attachment", source_id="src_mail")

    def broken(e):
        raise ValueError("unreadable receipt")

    for attempt in (1, 2, 3):
        assert queue.process_pending(db, "normaliser", broken, retry_after_seconds=0) == 0
    assert delivery(db, event["id"], "normaliser") == ("dead", 3)
    doc = db.execute("select doc from raw_items where id = 'raw_q1'").fetchone()[0]
    assert doc["processing_status"] == "failed" and doc["error"]["message"] == "unreadable receipt"
    assert queue.process_pending(db, "normaliser", broken, retry_after_seconds=0) == 0  # dead stays dead


def test_a_failed_attempt_writes_nothing_and_the_retry_writes_once(db):
    """Done only after the handler committed: a crash rolls its writes back, re-delivery writes exactly once."""
    db.execute("create table if not exists q_test (event_id text primary key)")
    db.commit()
    event = emit(db)
    calls = []

    def handler(e):
        calls.append(e["id"])
        db.execute("insert into q_test (event_id) values (%s) on conflict do nothing", (e["id"],))
        if len(calls) == 1:
            raise RuntimeError("crash after writing")

    # retry_after_seconds=0: the retry comes in the same pass; the crashed attempt's insert was rolled back
    assert queue.process_pending(db, "finance", handler, retry_after_seconds=0) == 1
    assert calls == [event["id"], event["id"]]
    assert db.execute("select count(*) from q_test").fetchone()[0] == 1
    assert delivery(db, event["id"], "finance") == ("done", 2)
    db.execute("drop table q_test")
    db.commit()


def test_first_types_are_taken_first(db):
    later = emit(db, "forecast.updated", forecast_id="fc_1")
    urgent = emit(db, "match.suggested", match_id="mat_1")
    order = []
    queue.process_pending(db, "agents", lambda e: order.append(e["id"]), first_types=["match.suggested"])
    assert order == [urgent["id"], later["id"]]


def test_a_failing_on_dead_still_ends_the_delivery(db):
    event = emit(db)

    def broken(e):
        raise ValueError("no")

    def on_dead(conn, e, error):
        raise RuntimeError("could not record")

    for _ in range(3):
        queue.process_pending(db, "finance", broken, retry_after_seconds=0, on_dead=on_dead)
    assert delivery(db, event["id"], "finance") == ("dead", 3)


def test_wait_wakes_up_on_a_new_event(db, db_url):
    listener = queue.listen(db_url)
    try:
        threading.Timer(0.3, lambda: emit(db)).start()
        started = time.monotonic()
        queue.wait(listener, timeout=10)
        assert time.monotonic() - started < 5
        started = time.monotonic()
        queue.wait(listener, timeout=0.5)  # nothing new: returns at the timeout
        assert time.monotonic() - started >= 0.4
    finally:
        listener.close()
