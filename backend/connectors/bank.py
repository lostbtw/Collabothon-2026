"""Bank connector (#22): polls the PSD2-shaped Sandbox Bank (contracts/bank-sim-api.md) for booked lines.

Cursor: `<bookingDate>|<entryReference>` of the last line stored (the format of contracts/fixtures/source.json);
a bare `E000000731` is accepted too. Each poll asks for the lines after that reference (the delta), page by page.
A cursor pointing at a line we never stored (the invented ones in contracts/fixtures) is ignored and the source is
read from the beginning (base.py checks it against raw_items).
Idempotency key: sha256 of `bank:<account id>:<entryReference>`. RawItem kind `bank_transaction`, payload = the
booked line exactly as the bank sent it (role 3's normaliser reads it).

Environment: ORDO_BANK_URL (default http://localhost:8081), ORDO_BANK_TOKEN (default demo-token, a Secret on the cluster).
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx
import psycopg

from backend.connectors.base import AuthError, Connector, ConnectorError, FetchedItem, FetchResult

PAGE_SIZE = 500
REF_RE = re.compile(r"E\d{9}$")


def bank_url() -> str:
    return os.environ.get("ORDO_BANK_URL", "http://localhost:8081")


def bank_token() -> str:
    return os.environ.get("ORDO_BANK_TOKEN", "demo-token")


def make_client(timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(base_url=bank_url(), timeout=timeout)


def reference_of(cursor: str | None) -> str | None:
    """`2026-11-21|E000000731` or `E000000731` -> `E000000731`; anything else -> None (start from the beginning)."""
    if not cursor:
        return None
    ref = cursor.rsplit("|", 1)[-1].strip()
    return ref if REF_RE.fullmatch(ref) else None


def account_for_source(conn: psycopg.Connection, source: dict[str, Any]) -> str:
    """The bank account a source polls: the Account whose source_id is this source (the same link role 3 uses),
    else `config_public.account_id`, else the naming convention src_bank_<x> -> acc_<x>."""
    row = conn.execute("select id from accounts where doc->>'source_id' = %s order by id limit 1",
                       (source["id"],)).fetchone()
    conn.commit()
    if row:
        return row[0]
    configured = (source.get("config_public") or {}).get("account_id")
    if configured:
        return configured
    return "acc_" + source["id"].removeprefix("src_bank_").removeprefix("src_")


class BankConnector(Connector):
    connector = "bank_psd2"
    key_prefix = "bank"

    def __init__(self, source: dict[str, Any], account_id: str, client: httpx.Client, *,
                 token: str | None = None, page_size: int = PAGE_SIZE):
        super().__init__(source)
        self.account_id = account_id
        self.client = client
        self.token = token or bank_token()
        self.page_size = page_size

    def key_scope(self) -> str:
        return self.account_id

    def cursor_external_id(self, cursor: str | None) -> str | None:
        return reference_of(cursor)

    def fetch(self, cursor: str | None) -> FetchResult:
        lines, more = self._page(reference_of(cursor), self.page_size)
        items = [
            FetchedItem(
                kind="bank_transaction",
                external_id=line["entryReference"],
                payload=line,
                metadata={"account_id": self.account_id, "booking_date": line.get("bookingDate")},
            )
            for line in lines
        ]
        new_cursor = f"{lines[-1].get('bookingDate', '')}|{lines[-1]['entryReference']}" if lines else cursor
        return FetchResult(items=items, cursor=new_cursor, more=more)

    def _page(self, after: str | None, limit: int) -> tuple[list[dict[str, Any]], bool]:
        """One page of booked lines after `after`, and whether another page follows."""
        params: dict[str, Any] = {"bookingStatus": "booked", "limit": limit}
        if after:
            params["entryReferenceFrom"] = after
        try:
            resp = self.client.get(
                f"/v1/accounts/{self.account_id}/transactions", params=params,
                headers={"Authorization": f"Bearer {self.token}", "Consent-ID": "demo"},
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"bank unreachable: {exc.__class__.__name__}: {exc}", code="bank_unreachable") from exc
        if resp.status_code in (401, 403):
            raise AuthError(f"bank refused the credentials (HTTP {resp.status_code})")
        if resp.status_code == 404:
            raise ConnectorError(f"bank does not know account {self.account_id}", code="account_unknown",
                                 retryable=False)
        if resp.status_code >= 400:
            raise ConnectorError(f"bank answered HTTP {resp.status_code}", code=f"http_{resp.status_code}",
                                 retryable=resp.status_code >= 500 or resp.status_code == 429)
        try:
            body = resp.json()
            lines: list[dict[str, Any]] = body["transactions"]["booked"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ConnectorError(f"bank sent an unreadable answer: {exc}", code="bad_response") from exc
        return lines, bool(lines) and "next" in (body.get("_links") or {})
