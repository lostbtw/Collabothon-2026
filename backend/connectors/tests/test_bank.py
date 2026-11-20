"""Bank connector (#22) against the real Sandbox Bank (sim/bank, served in-process) and the real tables."""
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from backend.connectors import main as connectors
from backend.connectors.bank import BankConnector, account_for_source, reference_of
from backend.connectors.base import run_once
from backend.db.store import Store

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim" / "bank"))
from bank_sim.app import create_app as create_bank  # noqa: E402
from bank_sim.store import Store as BankStore  # noqa: E402

FIXTURES = ROOT / "contracts" / "fixtures"
TOKEN = "test-token"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}


def fixture(entity: str, id_: str) -> dict:
    return next(d for d in json.loads((FIXTURES / f"{entity}.json").read_text(encoding="utf-8")) if d["id"] == id_)


def add_source(db, source_id: str, account_id: str, **override) -> dict:
    """The fixture Source with a fresh cursor (the fixture's own cursor is mock data), and its Account."""
    source = {**fixture("source", source_id), "cursor": None, "items_total": 0, "last_error": None,
              "next_run_at": None, **override}
    db.execute("insert into sources (id, company_id, doc) values (%s, %s, %s)",
               (source["id"], source["company_id"], Jsonb(source)))
    account = fixture("account", account_id)
    db.execute("insert into accounts (id, company_id, doc) values (%s, %s, %s) on conflict do nothing",
               (account["id"], account["company_id"], Jsonb(account)))
    db.commit()
    return source


@pytest.fixture
def bank():
    """The Sandbox Bank app; a TestClient is an httpx.Client, so the connector talks to it exactly as over HTTP."""
    with TestClient(create_bank(BankStore(), token=TOKEN)) as client:
        yield client


@pytest.fixture
def pln(db):
    return add_source(db, "src_bank_pln", "acc_pln")


def inject(bank, ref_date="2026-11-20", amount="-180.62", account="acc_pln", **kw):
    body = {"accountId": account, "bookingDate": ref_date, "amount": amount, "creditorName": "PIXELBOARD (SAMPLE)",
            "remittance": "PIXELBOARD.COM* 45.00 USD KARTA *4417", **kw}
    r = bank.post("/admin/transactions", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


def connector(db, source, bank, **kw):
    return BankConnector(source, account_for_source(db, source), bank, token=TOKEN, **kw)


def poll(db, source, bank, **kw):
    return run_once(db, connector(db, source, bank, **kw), sleep=lambda s: None)


def raw_items(db, source_id="src_bank_pln"):
    return Store(db).list("raw_item", source_id=source_id)


# ---------- acceptance 1: an injected line becomes exactly one RawItem within one poll ----------
def test_injected_line_becomes_one_raw_item_in_one_poll(db, bank, pln):
    line = inject(bank)
    result = poll(db, pln, bank)
    assert result["status"] == "success" and result["items_new"] == 1
    [item] = raw_items(db)
    assert item["kind"] == "bank_transaction"
    assert item["external_id"] == line["entryReference"] == "E000000001"
    assert item["payload"] == line  # exactly what the bank sent
    assert item["metadata"] == {"account_id": "acc_pln", "booking_date": "2026-11-20"}
    assert Store(db).get("source", "src_bank_pln")["cursor"] == "2026-11-20|E000000001"


# ---------- acceptance 2: running twice creates nothing new ----------
def test_second_poll_creates_nothing(db, bank, pln):
    inject(bank)
    poll(db, pln, bank)
    again = poll(db, pln, bank)
    assert again["status"] == "success" and again["items_fetched"] == 0 and again["items_new"] == 0
    assert len(raw_items(db)) == 1


def test_only_new_lines_are_fetched(db, bank, pln):
    inject(bank)
    poll(db, pln, bank)
    inject(bank, amount="-5.00")
    inject(bank, amount="-6.00")
    result = poll(db, pln, bank)
    assert result["items_fetched"] == 2 and result["items_new"] == 2
    assert sorted(i["external_id"] for i in raw_items(db)) == ["E000000001", "E000000002", "E000000003"]


def test_pages_are_followed_in_one_poll(db, bank, pln):
    for i in range(5):
        inject(bank, amount=f"-{i + 1}.00")
    result = poll(db, pln, bank, page_size=2)
    assert result["items_new"] == 5
    assert Store(db).get("source", "src_bank_pln")["cursor"].endswith("|E000000005")


def test_lines_hidden_by_the_as_of_date_arrive_when_it_moves(db, bank, pln):
    inject(bank, ref_date="2026-11-10")
    inject(bank, ref_date="2026-11-25")
    bank.post("/admin/clock", json={"now": "2026-11-20", "accountId": "acc_pln"}, headers=ADMIN)
    assert poll(db, pln, bank)["items_new"] == 1
    bank.post("/admin/clock", json={"now": "2026-11-30", "accountId": "acc_pln"}, headers=ADMIN)
    assert poll(db, pln, bank)["items_new"] == 1
    assert len(raw_items(db)) == 2


def test_raw_item_feeds_role_3s_normaliser(db, bank, pln):
    """The payload is what backend/pipeline reads: the line normalises into a valid Transaction."""
    from backend.db.contracts import MODELS
    from backend.pipeline.normalise import normalise_bank_line

    inject(bank)
    poll(db, pln, bank)
    txn = normalise_bank_line(raw_items(db)[0], fixture("account", "acc_pln"))
    MODELS["transaction"].model_validate(txn)
    assert txn["account_id"] == "acc_pln" and txn["external_id"] == "E000000001"


# ---------- failures ----------
def test_wrong_token_sets_the_source_to_error(db, bank, pln):
    c = BankConnector(pln, "acc_pln", bank, token="wrong")
    result = run_once(db, c, sleep=lambda s: None)
    assert result["status"] == "failed" and result["error"]["code"] == "auth_failed"
    assert Store(db).get("source", "src_bank_pln")["status"] == "error"


def test_unknown_account_is_not_retried(db, bank, pln):
    waited = []
    result = run_once(db, BankConnector(pln, "acc_nope", bank, token=TOKEN), sleep=waited.append)
    assert waited == [] and result["error"]["code"] == "account_unknown"
    assert Store(db).get("source", "src_bank_pln")["status"] == "error"


def test_unreachable_bank_is_retried_then_degraded(db, pln):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    waited = []
    with httpx.Client(base_url="http://bank.invalid", transport=httpx.MockTransport(down)) as client:
        result = run_once(db, BankConnector(pln, "acc_pln", client, token=TOKEN), sleep=waited.append)
    assert waited == [5, 20, 60]
    assert result["status"] == "failed" and result["error"]["code"] == "bank_unreachable"
    assert Store(db).get("source", "src_bank_pln")["status"] == "degraded"


def test_server_error_is_retried(db, pln):
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"transactions": {"booked": [], "pending": []}})

    with httpx.Client(base_url="http://bank.invalid", transport=httpx.MockTransport(flaky)) as client:
        result = run_once(db, BankConnector(pln, "acc_pln", client, token=TOKEN), sleep=lambda s: None)
    assert result["status"] == "success" and result["attempt"] == 2


# ---------- helpers ----------
def test_cursor_formats():
    assert reference_of("2026-11-21|E000000731") == "E000000731"
    assert reference_of("E000000731") == "E000000731"
    assert reference_of(None) is None and reference_of("") is None and reference_of("garbage") is None


def test_account_comes_from_the_accounts_table_then_config_then_convention(db, pln):
    assert account_for_source(db, pln) == "acc_pln"
    assert account_for_source(db, {"id": "src_x", "config_public": {"account_id": "acc_cfg"}}) == "acc_cfg"
    assert account_for_source(db, {"id": "src_bank_eur", "config_public": {}}) == "acc_eur"


# ---------- the process: schedule, "sync now", recovery, demo mode ----------
def test_tick_polls_due_sources_and_respects_next_run_at(db, bank, pln):
    inject(bank)
    now = datetime.now(UTC)
    [first] = _tick(db, bank, now, first=True)
    assert first["trigger"] == "startup" and first["items_new"] == 1
    assert _tick(db, bank, now) == []  # not due again until next_run_at
    assert len(_tick(db, bank, now + timedelta(seconds=61))) == 1


def _tick(db, bank, now, first=False):
    """tick() with the test token (the process reads ORDO_BANK_TOKEN)."""
    os.environ["ORDO_BANK_TOKEN"] = TOKEN
    try:
        return connectors.tick(db, bank, now=now, first=first, sleep=lambda s: None)
    finally:
        del os.environ["ORDO_BANK_TOKEN"]


def test_tick_skips_sources_without_a_connector_and_paused_ones(db, bank, pln):
    mail = {**fixture("source", "src_mail"), "next_run_at": None}
    db.execute("insert into sources (id, company_id, doc) values (%s, %s, %s)", (mail["id"], mail["company_id"], Jsonb(mail)))
    db.execute("""update sources set doc = doc || '{"status": "paused"}'::jsonb where id = 'src_bank_pln'""")
    db.commit()
    assert _tick(db, bank, datetime.now(UTC)) == []


def test_sync_now_button_is_picked_up(db, db_url, bank, pln):
    from backend.api.app import create_app as create_api
    from backend.db.seed import seed

    seed(db)  # the API checks that the company exists
    inject(bank)
    with TestClient(create_api(database_url=db_url)) as api:
        run = api.post("/api/v1/sources/src_bank_pln/sync").json()
        [result] = _tick(db, bank, datetime.now(UTC))  # adopted once, not run a second time by the schedule
        assert result["id"] == run["id"] and result["trigger"] == "manual" and result["status"] == "success"
        # acceptance 4: the Sources page data is live
        src = next(s for s in api.get("/api/v1/sources?company_id=co_borsuk").json()["items"] if s["id"] == "src_bank_pln")
        assert src["status"] == "connected" and src["last_synced_at"] and src["items_total"] == 1
        runs = api.get("/api/v1/sync-runs?source_id=src_bank_pln").json()["items"]
        assert runs[0]["id"] == run["id"] and runs[0]["status"] == "success"


def test_recover_closes_runs_left_running_by_a_dead_process(db, pln):
    stale = {"id": "run_stale", "source_id": "src_bank_pln", "connector": "bank_psd2", "trigger": "schedule",
             "started_at": "2026-11-21T10:00:00Z", "status": "running"}
    Store(db).add("sync_run", stale, company_id="co_borsuk")
    db.execute("""update sources set doc = doc || '{"status": "syncing"}'::jsonb where id = 'src_bank_pln'""")
    db.commit()
    assert connectors.recover_interrupted(db) == 1
    run = Store(db).get("sync_run", "run_stale")
    assert run["status"] == "failed" and run["error"]["code"] == "interrupted"
    assert Store(db).get("source", "src_bank_pln")["status"] == "degraded"


# ---------- the invented cursors of contracts/fixtures heal themselves ----------
def test_fixture_cursor_is_detected_and_the_source_starts_over(db, bank):
    # exactly what `python -m backend.db fixtures` leaves: "already read up to E000000731, 731 items"
    add_source(db, "src_bank_pln", "acc_pln", cursor="2026-11-21|E000000731", items_total=731)
    inject(bank)
    inject(bank, amount="-5.00")
    result = poll(db, add_source_noop(db), bank)
    assert result["items_new"] == 2
    src = Store(db).get("source", "src_bank_pln")
    assert src["cursor"] == "2026-11-20|E000000002"
    assert src["items_total"] == 2  # counted in the database, not 731 + 2


def add_source_noop(db):
    return Store(db).get("source", "src_bank_pln")


def test_fixture_cursor_that_matches_a_real_line_is_still_not_trusted(db, bank):
    """Found live: the pizzeria fixture says E000001125, and the real bank's last line IS E000001125.
    The cursor is still not ours (that line is not in our database), so everything is read."""
    for i in range(3):
        inject(bank, amount=f"-{i + 1}.00")
    add_source(db, "src_bank_pln", "acc_pln", cursor="2026-11-20|E000000003", items_total=3)
    result = poll(db, add_source_noop(db), bank)
    assert result["items_new"] == 3 and result["cursor_before"] == "2026-11-20|E000000003"
    assert Store(db).get("source", "src_bank_pln")["items_total"] == 3


def test_fixture_schedule_a_day_ahead_does_not_block_the_first_poll(db, bank):
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    add_source(db, "src_bank_pln", "acc_pln", next_run_at=tomorrow)
    inject(bank)
    assert len(_tick(db, bank, datetime.now(UTC))) == 1  # not first pass, still due: the time was not ours


def test_fixture_cursor_with_an_empty_bank_is_cleared(db, bank):
    add_source(db, "src_bank_pln", "acc_pln", cursor="2026-11-21|E000000731", items_total=731)
    result = poll(db, add_source_noop(db), bank)
    assert result["status"] == "success" and result["items_new"] == 0
    src = Store(db).get("source", "src_bank_pln")
    assert src["cursor"] is None and src["items_total"] == 0
    inject(bank)  # the first real line then arrives normally
    assert poll(db, add_source_noop(db), bank)["items_new"] == 1


def test_a_valid_cursor_is_kept_when_nothing_is_new(db, bank, pln):
    inject(bank)
    poll(db, pln, bank)
    again = poll(db, add_source_noop(db), bank)
    assert again["items_fetched"] == 0  # nothing re-read
    assert Store(db).get("source", "src_bank_pln")["cursor"] == "2026-11-20|E000000001"


def test_counter_matches_the_database_even_after_a_manual_reset(db, bank, pln):
    inject(bank)
    inject(bank, amount="-5.00")
    poll(db, pln, bank)
    assert connectors.reset_bank_cursors(db) == 1  # the manual tool still exists; it is no longer needed
    again = poll(db, add_source_noop(db), bank)
    assert (again["items_new"], again["items_duplicate"]) == (0, 2)
    assert Store(db).get("source", "src_bank_pln")["items_total"] == 2  # not 0


def test_demo_interval(db, bank, pln):
    connectors.apply_demo_intervals(db)
    assert Store(db).get("source", "src_bank_pln")["poll_interval_seconds"] == 15


# ---------- acceptance 3: the pizzeria, 1,125 RawItems (organisers' file, not in Git) ----------
REAL = os.environ.get("BANK_TEST_CSV")


@pytest.mark.skipif(not (REAL and Path(REAL).exists()), reason="BANK_TEST_CSV not set")
def test_pizzeria_is_ingested_through_the_connector(db, bank):
    pizzeria = add_source(db, "src_bank_pizzeria", "acc_pizzeria")
    r = bank.post("/admin/load-csv", content=Path(REAL).read_bytes(), headers={**ADMIN, "Content-Type": "text/csv"})
    assert r.json()["lines"] == 1125
    result = poll(db, pizzeria, bank)
    assert result["status"] == "success" and result["items_new"] == 1125
    assert len(raw_items(db, "src_bank_pizzeria")) == 1125
    assert poll(db, pizzeria, bank)["items_new"] == 0
    assert Store(db).get("source", "src_bank_pizzeria")["cursor"] == "2025-12-31|E000001125"
