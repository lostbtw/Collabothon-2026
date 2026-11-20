"""Forecast endpoints. The numbers are role 4's (finance engine); this module only serves and routes them.

Until role 4's engine is importable as `backend.finance.engine`, recompute/events/scenario are stand-ins: they
copy the latest stored forecast and record the owner's event or the scenario request without recomputing.
"""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends

from backend.api.deps import ApiError, company_id, conn, get_or_404, store
from backend.api.forecasting import add_forecast_event
from backend.api.ports import finance_engine, latest_base_forecast, reissue_forecast
from backend.db.store import Store

router = APIRouter()


def latest_forecast(c: psycopg.Connection, company: str) -> dict[str, Any]:
    found = latest_base_forecast(c, company)
    if found is None:
        raise ApiError(404, "not_found", f"No forecast for {company} yet")
    return found


@router.get("/forecast/latest")
def get_latest(company: str = Depends(company_id), horizon_days: int = 45, c: psycopg.Connection = Depends(conn)):
    return latest_forecast(c, company)


@router.get("/forecast/{id}")
def get_forecast(id: str, s: Store = Depends(store)):
    return get_or_404(s, "forecast", id)


@router.post("/forecast/recompute")
def recompute(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    engine = finance_engine()
    if engine:
        return engine.recompute(c, company)
    return latest_forecast(c, company)


@router.post("/forecast/events", status_code=201)
def add_event(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    event, forecast = add_forecast_event(c, company, {**body, "source": body.get("source", "owner_form")})
    if forecast is None:
        raise ApiError(409, "no_forecast", f"Event {event['id']} stored; {company} has no forecast to recompute yet")
    return forecast


@router.post("/forecast/scenario")
def scenario(body: dict[str, Any] = Body(...), company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    engine = finance_engine()
    if engine:
        return engine.scenario(c, company, body)
    base = latest_forecast(c, company)
    what = ", ".join(sorted(body)) or "no change"
    return reissue_forecast(c, company, base, scenario_of=base["id"],
                            assumptions=[*base["assumptions"], f"Scenario requested ({what}); stand-in copy, not recomputed"])
