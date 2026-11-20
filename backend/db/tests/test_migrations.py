"""Seam: migrations against a real Postgres."""
import psycopg

from backend.db.migrate import migrate


def test_migrations_create_every_contract_table(db):
    tables = {r[0] for r in db.execute("select tablename from pg_tables where schemaname = 'public'")}
    expected = {
        "companies", "people", "sources", "sync_runs", "raw_items", "documents", "accounts",
        "transactions", "counterparties", "matches", "ledger_entries", "forecasts",
        "recommendations", "approvals", "outbox", "outbox_delivery",
    }
    assert expected <= tables


def test_migrations_apply_twice_without_change(db_url):
    with psycopg.connect(db_url) as conn:
        assert migrate(conn) == []
