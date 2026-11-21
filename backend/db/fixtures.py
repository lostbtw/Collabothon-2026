"""Load contracts/fixtures as demo data (idempotent); company_id comes from the parent when missing."""
import json
from pathlib import Path

import psycopg

from backend.db.events import publish
from backend.db.seed import seed
from backend.db.store import Store

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"

# parents first, so children can look their company up
ORDER = [
    "source", "account", "counterparty", "sync_run", "raw_item", "document", "transaction",
    "match", "ledger_entry", "forecast", "recommendation", "approval",
]


def read(entity: str) -> list[dict]:
    return json.loads((FIXTURES / f"{entity}.json").read_text(encoding="utf-8"))


def company_for(store: Store, entity: str, doc: dict) -> str | None:
    if doc.get("company_id"):
        return doc["company_id"]
    parent = {
        "sync_run": ("source", doc.get("source_id")),
        "raw_item": ("source", doc.get("source_id")),
        "transaction": ("account", doc.get("account_id")),
        "match": ("document", doc.get("document_id")),
        "approval": (doc.get("subject_type"), doc.get("subject_id")),
    }.get(entity)
    if not parent or not parent[0] or not parent[1]:
        return None
    return store.company_of(*parent)


def load_fixtures(conn: psycopg.Connection) -> None:
    seed(conn)
    store = Store(conn)
    for entity in ORDER:
        for doc in read(entity):
            store.put(entity, doc, company_id=company_for(store, entity, doc))
    for event in read("event"):
        publish(conn, event)
