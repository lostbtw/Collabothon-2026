"""Apply backend/db/migrations/*.sql in name order, each once. Run: `uv run python -m backend.db migrate`."""
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"

# Tables holding reference data written by migrations; tests never empty them.
REFERENCE_TABLES = {"schema_migrations", "outbox_subscription"}


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())"
    )
    conn.commit()
    done = {r[0] for r in conn.execute("select name from schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied
