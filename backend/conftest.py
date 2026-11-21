"""Shared test fixtures for every backend role.

`db_url`: a fresh, migrated Postgres database for this test session.
  - CI sets ORDO_TEST_DATABASE_URL (a Postgres service).
  - Locally without Docker: `uv sync --group localdb` installs pgserver, which runs a private Postgres in .venv/.
  - Neither available: database tests are skipped, the rest still run.
`db`: a connection to that database; every table is emptied after each test (reference tables are kept).
"""
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_model_calls(monkeypatch):
    """Tests never reach a model endpoint; tests that need a model pass a fake client."""
    monkeypatch.setenv("ORDO_LLM_ENABLED", "0")
    monkeypatch.delenv("ORDO_GUARDRAILS_URL", raising=False)


def _server_url() -> str:
    url = os.environ.get("ORDO_TEST_DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        pytest.skip("no test database: set ORDO_TEST_DATABASE_URL or run `uv sync --group localdb`")
    server = pgserver.get_server(ROOT / ".venv" / "pgdata-test", cleanup_mode=None)
    return server.get_uri()


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + name))


@pytest.fixture(scope="session")
def db_url():
    from backend.db.migrate import migrate

    server = _server_url()
    name = f"ordo_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    url = _with_database(server, name)
    with psycopg.connect(url) as conn:
        migrate(conn)
    yield url
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def db(db_url):
    from backend.db.migrate import REFERENCE_TABLES

    with psycopg.connect(db_url) as conn:
        yield conn
        conn.rollback()
        tables = [
            r[0]
            for r in conn.execute(
                "select tablename from pg_tables where schemaname = 'public'"
            ).fetchall()
            if r[0] not in REFERENCE_TABLES
        ]
        if tables:
            conn.execute("truncate " + ", ".join(f'"{t}"' for t in tables) + " cascade")
        conn.commit()


class TraceRecorder:
    def __init__(self):
        self.spans, self.outputs, self.tags, self.open = [], {}, {}, []

    def span(self, name, inputs=None, span_type="CHAIN"):
        from contextlib import contextmanager

        @contextmanager
        def opened():
            self.spans.append((name, len(self.open), inputs or {}))
            self.open.append(name)
            try:
                yield name
            finally:
                self.open.pop()

        return opened()

    def record_outputs(self, current, value):
        if current is not None:
            self.outputs[current] = value

    def tag(self, **tags):
        self.tags.update({key: value for key, value in tags.items() if value is not None})

    def trace_id(self):
        return "tr-test" if self.open else None


@pytest.fixture
def traced(monkeypatch):
    from backend import tracing

    recorder = TraceRecorder()
    monkeypatch.setattr(tracing, "span", recorder.span)
    monkeypatch.setattr(tracing, "outputs", recorder.record_outputs)
    monkeypatch.setattr(tracing, "tag", recorder.tag)
    monkeypatch.setattr(tracing, "trace_id", recorder.trace_id)
    return recorder
