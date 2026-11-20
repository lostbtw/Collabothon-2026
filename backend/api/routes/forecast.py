"""Forecast endpoints. The numbers are role 4's (finance engine); this module only serves and routes them.

Until role 4's engine is importable as `backend.finance.engine`, recompute/events/scenario are stand-ins: they
copy the latest stored forecast and record the owner's event or the scenario request without recomputing.
"""
import importlib.util
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends

from backend.api.deps import ApiError, company_id, conn, get_or_404, new_id, now_iso, store
from backend.db.store import Store

router = APIRouter()


def finance_engine():
    """Role 4's engine module, or None while it does not exist yet."""
    try:
        if importlib.util.find_spec("backend.finance.engine") is None:
            return None
    except ModuleNotFoundError:
        return None
    import backend.finance.engine as engine

    return engine


def latest_forecast(s: Store, company: str) -> dict[str, Any]:
    found = [f for f in s.list("forecast", company_id=company) if not f.get("scenario_of")]
    if not found:
        raise ApiError(404, "not_found", f"No forecast for {company} yet")
    return found[0]


def _new_version(base: dict[str, Any], **changes) -> dict[str, Any]:
    return {**base, "id": new_id("fc"), "generated_at": now_iso(), "inputs_hash": None, **changes}


@router.get("/forecast/latest")
def get_latest(company: str = Depends(company_id), horizon_days: int = 45, s: Store = Depends(store)):
    return latest_forecast(s, company)


@router.get("/forecast/{id}")
def get_forecast(id: str, s: Store = Depends(store)):
    return get_or_404(s, "forecast", id)


@router.post("/forecast/recompute")
def recompute(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    engine = finance_engine()
    if engine:
        return engine.recompute(c, company)
    return latest_forecast(Store(c), company)


@router.post("/forecast/events", status_code=201)
def add_event(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    for field in ("label", "date_from", "date_to", "effect"):
        if field not in body:
            raise ApiError(422, "invalid_request", f"{field} is required")
    event = {"id": new_id("fev"), "label": body["label"], "date_from": body["date_from"], "date_to": body["date_to"],
             "effect": body["effect"], "amount": body.get("amount"), "source": body.get("source", "owner_form")}
    engine = finance_engine()
    if engine:
        return engine.add_event(c, company, event)
    s = Store(c)
    base = latest_forecast(s, company)
    updated = _new_version(base, events=[*base.get("events", []), event])
    s.add("forecast", updated, company_id=company)
    return updated


@router.post("/forecast/scenario")
def scenario(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    engine = finance_engine()
    if engine:
        return engine.scenario(c, company, body)
    s = Store(c)
    base = latest_forecast(s, company)
    what = ", ".join(sorted(body)) or "no change"
    result = _new_version(base, scenario_of=base["id"],
                          assumptions=[*base["assumptions"], f"Scenario requested ({what}); stand-in copy, not recomputed"])
    s.add("forecast", result, company_id=company)
    return result
