"""Accounts, Transactions, Counterparties."""
from decimal import Decimal

import psycopg
from fastapi import APIRouter, Depends, Query

from backend.api import stand_ins
from backend.api.deps import company_id, conn, get_or_404, store
from backend.api.money import money
from backend.db.store import Store

router = APIRouter()


def base_currency(c: psycopg.Connection, company: str) -> str:
    return c.execute("select base_currency from companies where id = %s", (company,)).fetchone()[0]


@router.get("/accounts")
def list_accounts(company: str = Depends(company_id), s: Store = Depends(store), c: psycopg.Connection = Depends(conn)):
    accounts = s.list("account", company_id=company)
    base = base_currency(c, company)
    total = sum(
        (stand_ins.convert(Decimal(a["balance"]["amount"]), a["balance"]["currency"], base)
         for a in accounts if a.get("include_in_liquidity") and a.get("balance")),
        Decimal(0),
    )
    return {"items": accounts, "total_liquidity_base": money(total, base)}


@router.get("/transactions")
def list_transactions(company: str = Depends(company_id), account_id: str | None = None, from_: str | None = Query(None, alias="from"),
                      to: str | None = None, match_status: str | None = None, series: str | None = None,
                      cursor: str | None = None, s: Store = Depends(store)):
    where = {k: v for k, v in {"account_id": account_id, "match_status": match_status}.items() if v}
    items = s.list("transaction", company_id=company, **where)
    items = [t for t in items
             if (not from_ or t["booking_date"] >= from_) and (not to or t["booking_date"] <= to)
             and (not series or t.get("recurring_series_id") == series)]
    return {"items": items, "next_cursor": None}


@router.get("/transactions/{id}")
def get_transaction(id: str, s: Store = Depends(store)):
    return get_or_404(s, "transaction", id)


@router.get("/counterparties")
def list_counterparties(company: str = Depends(company_id), s: Store = Depends(store)):
    return {"items": s.list("counterparty", company_id=company)}
