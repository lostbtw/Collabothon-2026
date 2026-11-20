"""One command for a local API with demo data: `uv sync --group localdb && uv run python -m backend.api.dev`.

Uses ORDO_DATABASE_URL if set, otherwise starts a private Postgres in .venv/pgdata-dev (pgserver, no Docker),
then migrates, seeds, loads contracts/fixtures and serves on http://localhost:8080/api/v1.
"""
import os
import sys
from pathlib import Path

import psycopg
import uvicorn

from backend.api.app import create_app
from backend.db.fixtures import load_fixtures
from backend.db.migrate import migrate

ROOT = Path(__file__).resolve().parents[2]


def local_database_url() -> str:
    if os.environ.get("ORDO_DATABASE_URL"):
        return os.environ["ORDO_DATABASE_URL"]
    try:
        import pgserver
    except ImportError:
        sys.exit("No ORDO_DATABASE_URL and no local Postgres: run `uv sync --group localdb` first.")
    server_url = pgserver.get_server(ROOT / ".venv" / "pgdata-dev", cleanup_mode=None).get_uri()
    with psycopg.connect(server_url, autocommit=True) as admin:
        if not admin.execute("select 1 from pg_database where datname = 'ordo'").fetchone():
            admin.execute("create database ordo")
    return server_url.rsplit("/", 1)[0] + "/ordo"


def main() -> None:
    url = local_database_url()
    with psycopg.connect(url) as conn:
        migrate(conn)
        load_fixtures(conn)
    print(f"database: {url}")
    uvicorn.run(create_app(database_url=url), host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
