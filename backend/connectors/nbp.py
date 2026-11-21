"""NBP exchange-rate connector: one RawItem per published table A (mid rates), 3 years of history on the first run."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import psycopg

from backend.connectors.base import Connector, ConnectorError, FetchedItem, FetchResult

WINDOW_DAYS = 93
DEFAULT_HISTORY_DAYS = 1095


def nbp_url() -> str:
    return os.environ.get("ORDO_NBP_URL", "https://api.nbp.pl")


def make_nbp_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(base_url=nbp_url(), timeout=timeout, headers={"Accept": "application/json"})


def _cursor_parts(cursor: str | None) -> tuple[date | None, str | None]:
    if not cursor:
        return None, None
    left, _, right = cursor.partition("|")
    if not right:
        return None, left.strip() or None
    try:
        return date.fromisoformat(left.strip()), right.strip() or None
    except ValueError:
        return None, right.strip() or None


class NbpConnector(Connector):
    connector = "fx_rates"
    key_prefix = "nbp"

    def __init__(self, source: dict[str, Any], client: httpx.Client, *, today: date | None = None):
        super().__init__(source)
        self.client = client
        self.today = today

    def key_scope(self) -> str:
        return "A"

    def cursor_external_id(self, cursor: str | None) -> str | None:
        return _cursor_parts(cursor)[1]

    def _today(self) -> date:
        return self.today or datetime.now(UTC).date()

    def _history_days(self) -> int:
        return int((self.source.get("config_public") or {}).get("history_days") or DEFAULT_HISTORY_DAYS)

    def fetch(self, cursor: str | None) -> FetchResult:
        last, _ = _cursor_parts(cursor)
        today = self._today()
        start = last + timedelta(days=1) if last else today - timedelta(days=self._history_days())
        while start <= today:
            end = min(start + timedelta(days=WINDOW_DAYS - 1), today)
            if all((start + timedelta(days=i)).weekday() >= 5 for i in range((end - start).days + 1)):
                start = end + timedelta(days=1)
                continue
            # For a day without a table NBP sometimes answers 500, not 404: just after the last stored table that means nothing new.
            tables = self._tables(start, end, quiet=bool(last) and (end - start).days <= 3)
            if tables:
                items = [
                    FetchedItem(
                        kind="fx_rate_table",
                        external_id=t["no"],
                        payload={"table": "A", "no": t["no"], "effectiveDate": t["effectiveDate"],
                                 "rates": {r["code"]: f"{r['mid']:.4f}" for r in t.get("rates", [])}},
                        metadata={"effective_date": t["effectiveDate"]},
                    )
                    for t in sorted(tables, key=lambda t: t["effectiveDate"])
                ]
                last_t = items[-1].payload
                return FetchResult(items=items, cursor=f"{last_t['effectiveDate']}|{last_t['no']}", more=end < today)
            start = end + timedelta(days=1)
        return FetchResult(items=[], cursor=cursor)

    def _tables(self, start: date, end: date, *, quiet: bool = False) -> list[dict[str, Any]]:
        path = f"/api/exchangerates/tables/A/{start.isoformat()}/{end.isoformat()}/"
        try:
            resp = self.client.get(path, params={"format": "json"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"NBP unreachable: {exc.__class__.__name__}: {exc}", code="nbp_unreachable") from exc
        if resp.status_code == 404:
            return []
        if quiet and resp.status_code >= 500:
            return []
        if resp.status_code >= 400:
            raise ConnectorError(f"NBP answered HTTP {resp.status_code} for {start}..{end}",
                                 code=f"http_{resp.status_code}",
                                 retryable=resp.status_code >= 500 or resp.status_code == 429)
        try:
            body = resp.json()
            return [t for t in body if t.get("no") and t.get("effectiveDate")]
        except (ValueError, AttributeError, TypeError) as exc:
            raise ConnectorError(f"NBP sent an unreadable answer: {exc}", code="bad_response") from exc


def rate_on(conn: psycopg.Connection, currency: str, on: date,
            rule: str = "pl_tax_prev_business_day") -> dict[str, str] | None:
    currency = currency.upper()
    if currency == "PLN":
        return {"rate": "1", "rate_date": on.isoformat(), "source": "PLN", "rule": rule}
    op = "<" if rule == "pl_tax_prev_business_day" else "<="
    row = conn.execute(
        f"""select doc->'payload'->>'effectiveDate', doc->'payload'->>'no', doc->'payload'->'rates'->>%s
            from raw_items
            where doc->>'kind' = 'fx_rate_table' and doc->'payload'->'rates' ? %s
              and doc->'payload'->>'effectiveDate' {op} %s
            order by doc->'payload'->>'effectiveDate' desc limit 1""",
        (currency, currency, on.isoformat()),
    ).fetchone()
    if row is None:
        return None
    effective, no, rate = row
    return {"rate": rate, "rate_date": effective, "source": f"NBP table A {no}", "rule": rule}


def history(conn: psycopg.Connection, currency: str, since: date | None = None) -> list[tuple[str, str]]:
    currency = currency.upper()
    rows = conn.execute(
        """select doc->'payload'->>'effectiveDate', doc->'payload'->'rates'->>%s
           from raw_items
           where doc->>'kind' = 'fx_rate_table' and doc->'payload'->'rates' ? %s
             and doc->'payload'->>'effectiveDate' >= %s
           order by 1""",
        (currency, currency, (since or date(1900, 1, 1)).isoformat()),
    ).fetchall()
    return [(d, r) for d, r in rows]
