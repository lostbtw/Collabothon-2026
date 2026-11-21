"""Read and write contract entities whole; a repeated idempotency key is a no-op.

    store = Store(conn)
    store.add("raw_item", item)        # True if stored, False if it (or its idempotency key) already exists
    store.put("match", match)          # insert or replace by id (state changes)
    store.get("match", "mat_412")      # dict or None
    store.list("recommendation", company_id="co_borsuk", status="new")
"""
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

# entity name -> (table, columns that list() may filter on besides company_id)
ENTITIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "source": ("sources", ("connector",)),
    "sync_run": ("sync_runs", ("source_id",)),
    "raw_item": ("raw_items", ("source_id", "idempotency_key", "processing_status")),
    "document": ("documents", ("status", "direction", "first_raw_item_id")),
    "account": ("accounts", ()),
    "transaction": ("transactions", ("account_id", "external_id", "match_status")),
    "counterparty": ("counterparties", ()),
    "match": ("matches", ("document_id", "match_type", "status")),
    "ledger_entry": ("ledger_entries", ("match_id", "type", "status", "approval_id")),
    "forecast": ("forecasts", ("inputs_hash", "scenario_of")),
    "recommendation": ("recommendations", ("agent", "type", "status", "control_level", "subject_id")),
    "approval": ("approvals", ("subject_type", "subject_id")),
}

# newest first: last written for entities the app creates, booking date for bank lines
_ORDER = {
    "sync_run": "seq desc",
    "forecast": "seq desc",
    "recommendation": "seq desc",
    "approval": "seq desc",
    "transaction": "booking_date desc",
}


class UnknownEntity(ValueError):
    pass


def _table(entity: str) -> tuple[str, tuple[str, ...]]:
    try:
        return ENTITIES[entity]
    except KeyError:
        raise UnknownEntity(entity) from None


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def add(self, entity: str, doc: dict[str, Any], *, company_id: str | None = None) -> bool:
        """Insert once. False when the id or one of the entity's idempotency keys already exists."""
        table, _ = _table(entity)
        cur = self.conn.execute(
            f"insert into {table} (id, company_id, doc) values (%s, %s, %s) on conflict do nothing",
            (doc["id"], company_id or doc.get("company_id"), Jsonb(doc)),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def put(self, entity: str, doc: dict[str, Any], *, company_id: str | None = None) -> None:
        """Insert or replace by id."""
        table, _ = _table(entity)
        self.conn.execute(
            f"""insert into {table} (id, company_id, doc) values (%s, %s, %s)
                on conflict (id) do update set doc = excluded.doc,
                    company_id = coalesce(excluded.company_id, {table}.company_id)""",
            (doc["id"], company_id or doc.get("company_id"), Jsonb(doc)),
        )
        self.conn.commit()

    def get(self, entity: str, id: str) -> dict[str, Any] | None:
        table, _ = _table(entity)
        row = self.conn.execute(f"select doc from {table} where id = %s", (id,)).fetchone()
        return row[0] if row else None

    def company_of(self, entity: str, id: str) -> str | None:
        table, _ = _table(entity)
        row = self.conn.execute(f"select company_id from {table} where id = %s", (id,)).fetchone()
        return row[0] if row else None

    def list(self, entity: str, *, company_id: str | None = None, limit: int | None = None, **where: Any) -> list[dict[str, Any]]:
        table, filters = _table(entity)
        clauses, params = [], []
        if company_id is not None:
            clauses.append("company_id = %s")
            params.append(company_id)
        for column, value in where.items():
            if column not in filters:
                raise ValueError(f"{entity} cannot be filtered on {column!r}")
            if isinstance(value, (list, tuple, set)):
                clauses.append(f"{column} = any(%s)")
                params.append(list(value))
            else:
                clauses.append(f"{column} = %s")
                params.append(value)
        sql = f"select doc from {table}"
        if clauses:
            sql += " where " + " and ".join(clauses)
        sql += f" order by {_ORDER.get(entity, 'id')}"
        if limit:
            sql += f" limit {int(limit)}"
        return [r[0] for r in self.conn.execute(sql, params).fetchall()]
