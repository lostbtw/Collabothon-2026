"""Shared pieces of every route: errors, the database connection, the Store, the company of a request."""
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import Depends, Query, Request

from backend.db.seed import companies
from backend.db.store import Store


class ApiError(Exception):
    """Raise to answer with the standard error shape {"error": {"code", "message"}}."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found(kind: str, id: str) -> ApiError:
    return ApiError(404, "not_found", f"No {kind} with id {id!r}")


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


def store(c: psycopg.Connection = Depends(conn)) -> Store:
    return Store(c)


def company_id(c: psycopg.Connection = Depends(conn), company_id: str | None = Query(None)) -> str:
    """?company_id=, default the first company (openapi conventions)."""
    known = [co["id"] for co in companies(c)]
    if company_id is None:
        if not known:
            raise ApiError(404, "not_found", "No company seeded; run `python -m backend.db setup`")
        return known[0]
    if company_id not in known:
        raise not_found("company", company_id)
    return company_id


def get_or_404(s: Store, entity: str, id: str) -> dict[str, Any]:
    doc = s.get(entity, id)
    if doc is None:
        raise not_found(entity.replace("_", " "), id)
    return doc


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def owner_of(c: psycopg.Connection, company: str) -> dict[str, Any]:
    """PersonRef of the company's owner: the person who makes every Decision in this single-user build."""
    row = c.execute(
        "select id, name, email from people where company_id = %s and role = 'owner' order by id limit 1", (company,)
    ).fetchone()
    if not row:
        return {"person_id": None, "name": "Owner", "role": "owner"}
    return {"person_id": row[0], "name": row[1], "email": row[2], "role": "owner"}
