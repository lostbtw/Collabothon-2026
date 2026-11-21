"""Owner screen endpoints; figures from backend/api/owner.py."""
import re
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends, Query, Response

from backend.api import owner
from backend.api.deps import ApiError, company_id, conn, not_found

router = APIRouter()
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month(month: str | None, c: psycopg.Connection, company: str) -> str:
    if month is None:
        as_of = str(c.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0])
        year, mon = int(as_of[:4]), int(as_of[5:7])
        return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
    if not MONTH.match(month):
        raise ApiError(422, "invalid_request", "month is YYYY-MM")
    return month


def _bad(exc: ValueError) -> ApiError:
    return ApiError(422, "invalid_request", str(exc))


@router.get("/settings")
def get_settings(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return owner.settings(c, company)


@router.patch("/settings")
def patch_settings(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    try:
        return owner.patch_settings(c, company, body)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/people")
def list_people(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return {"items": owner.people(c, company)}


@router.post("/people", status_code=201)
def add_person(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    try:
        return owner.add_person(c, company, body)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/people/{id}")
def change_person(id: str, body: dict[str, Any] = Body(...), company: str = Depends(company_id),
                  c: psycopg.Connection = Depends(conn)):
    try:
        return owner.update_person(c, company, id, body)
    except LookupError as exc:
        raise not_found("person", id) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/rules")
def list_rules(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return {"items": owner.rules(c, company)}


@router.delete("/rules/{id}", status_code=204)
def delete_rule(id: str, company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    if not owner.delete_rule(c, company, id):
        raise not_found("rule", id)
    return Response(status_code=204)


@router.patch("/transactions/{id}")
def change_transaction_type(id: str, body: dict[str, Any] = Body(...), company: str = Depends(company_id),
                            c: psycopg.Connection = Depends(conn)):
    if set(body) != {"category"}:
        raise ApiError(422, "invalid_request", "only category can be changed")
    try:
        return owner.set_transaction_category(c, company, id, body["category"])
    except LookupError as exc:
        raise not_found("transaction", id) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/people/costs")
def people_costs(month: str | None = Query(None), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return owner.people_costs(c, company, _month(month, c, company))


@router.get("/clients")
def clients(month: str | None = Query(None), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return owner.clients(c, company, _month(month, c, company))


@router.get("/subscriptions")
def subscriptions(month: str | None = Query(None), scope: str = Query("subscriptions", pattern="^(subscriptions|all)$"),
                  company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    if month is not None and not MONTH.match(month):
        raise ApiError(422, "invalid_request", "month is YYYY-MM")
    return owner.subscriptions(c, company, month, scope)


@router.get("/chat/sessions")
def chat_sessions(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    return {"items": owner.chat_sessions(c, company)}


@router.get("/chat/sessions/{session_id}")
def chat_session(session_id: str, company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    found = owner.chat_session(c, company, session_id)
    if found is None:
        raise not_found("chat", session_id)
    return found


@router.get("/balance/history")
def balance_history(days: int = Query(91, ge=7, le=400), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    found = owner.balance_history(c, company, days)
    if found is None:
        raise ApiError(404, "not_found", "No account with a reported balance")
    return found
