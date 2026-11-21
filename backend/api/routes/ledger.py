"""Ledger, its summary and the CSV export (role 4's data, served by role 5)."""
import csv
import io
import json
import zipfile
from collections import defaultdict
from decimal import Decimal

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from backend.api.deps import company_id, conn, store
from backend.api.money import amount_of, money
from backend.api.ports import finance_engine
from backend.api.routes.bank import base_currency
from backend.db.store import ENTITIES, Store

router = APIRouter()


def _entries(s: Store, company: str, from_: str | None, to: str | None, **where) -> list[dict]:
    items = s.list("ledger_entry", company_id=company, **where)
    return [e for e in items if (not from_ or e["date"] >= from_) and (not to or e["date"] <= to)]


@router.get("/ledger")
def list_ledger(company: str = Depends(company_id), from_: str | None = Query(None, alias="from"), to: str | None = None,
                category: str | None = None, status: str | None = None, paid_by: str | None = None,
                cursor: str | None = None, s: Store = Depends(store)):
    where = {"status": status} if status else {}
    items = _entries(s, company, from_, to, **where)
    items = [e for e in items if (not category or e["category"] == category) and (not paid_by or e.get("paid_by") == paid_by)]
    return {"items": items, "next_cursor": None}


GROUP_KEYS = {
    "category": lambda e: e["category"],
    "month": lambda e: e["date"][:7],
    "cost_behaviour": lambda e: e.get("cost_behaviour") or "unknown",
    "paid_by": lambda e: e.get("paid_by") or "unknown",
    "counterparty": lambda e: e.get("counterparty_id") or "unknown",
}


@router.get("/ledger/summary")
def ledger_summary(company: str = Depends(company_id), group_by: str = "category", from_: str | None = Query(None, alias="from"),
                   to: str | None = None, s: Store = Depends(store), c: psycopg.Connection = Depends(conn)):
    """Rows: plain sums over non-void entries in from/to (no LLM).

    Kpis: role 4's engine.ledger_kpis() (approved entries, the as-of year, not limited by from/to), or the stand-in
    below while the engine is not importable."""
    base = base_currency(c, company)
    entries = [e for e in _entries(s, company, from_, to) if e["status"] != "void"]
    key = GROUP_KEYS.get(group_by, GROUP_KEYS["category"])
    sums: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        sums[key(e)] += amount_of(e["amount_base"])
        counts[key(e)] += 1
    rows = [{"key": k, "amount_base": money(v, base), "change_pct": None, "entries": counts[k]}
            for k, v in sorted(sums.items(), key=lambda kv: kv[1])]

    engine = finance_engine()
    if engine is not None and hasattr(engine, "ledger_kpis"):
        return {"rows": rows, "kpis": engine.ledger_kpis(c, company)}

    owed = sum((amount_of(e["amount_base"]) for e in entries if e["type"] == "reimbursement_liability"), Decimal(0))
    paid = sum((amount_of(e["amount_base"]) for e in entries if e["type"] == "reimbursement_payout"), Decimal(0))
    vat_lost = sum((amount_of(e["vat"]["amount"]) for e in entries if e.get("vat") and not e["vat"]["deductible"]), Decimal(0))
    missing = len(s.list("transaction", company_id=company, match_status="missing_document"))
    kpis = {
        "reimbursements_owed": money(abs(owed) - abs(paid), base),
        "vat_lost_ytd": money(vat_lost, base),
        "documents_missing": missing,
    }
    return {"rows": rows, "kpis": kpis}


LEDGER_COLUMNS = ["id", "date", "cash_date", "type", "category", "amount", "currency", "amount_base", "base_currency",
                  "paid_by", "status", "counterparty_id", "document_id", "transaction_id", "match_id", "explanation"]


@router.get("/ledger/export")
def ledger_export(company: str = Depends(company_id), s: Store = Depends(store)):
    """Everything as CSV in one zip: the ledger flat, every other entity as id + JSON."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(LEDGER_COLUMNS)
        for e in s.list("ledger_entry", company_id=company):
            w.writerow([e["id"], e["date"], e.get("cash_date"), e["type"], e["category"], e["amount"]["amount"],
                        e["amount"]["currency"], e["amount_base"]["amount"], e["amount_base"]["currency"],
                        e.get("paid_by"), e["status"], e.get("counterparty_id"), e.get("document_id"),
                        e.get("transaction_id"), e.get("match_id"), e["explanation"]])
        z.writestr("ledger_entries.csv", out.getvalue())
        for entity in ENTITIES:
            if entity == "ledger_entry":
                continue
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["id", "json"])
            for doc in s.list(entity, company_id=company):
                w.writerow([doc["id"], json.dumps(doc, ensure_ascii=False)])
            z.writestr(f"{entity}s.csv", out.getvalue())
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="ordo-{company}.zip"'})
