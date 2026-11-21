"""/health, /companies, /fx/rates, /fx/exposure."""
import os
from datetime import date

import httpx
import psycopg
from fastapi import APIRouter, Depends, Query

from backend import settings
from backend.api import stand_ins
from backend.api.deps import ApiError, company_id, conn, now_iso
from backend.api.ports import finance_engine
from backend.connectors.nbp import rate_on
from backend.db.seed import companies

router = APIRouter()


def _llm_reachable(base_url: str) -> bool:
    """True when the model endpoint answers and accepts our token."""
    if os.environ.get("ORDO_LLM_ENABLED", "1") == "0":
        return False
    try:
        response = httpx.get(base_url.rstrip("/") + "/models", timeout=2.0, verify=settings.llm_verify(),
                             headers={"Authorization": f"Bearer {settings.llm_token()}"})
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("/health")
def health():
    base_url = settings.llm_base_url()
    return {
        "status": "ok",
        "llm": {"base_url": base_url, "model": settings.llm_model(), "reachable": _llm_reachable(base_url)},
        "demo_clock": now_iso(),
    }


@router.get("/companies")
def list_companies(c: psycopg.Connection = Depends(conn)):
    return {"items": companies(c)}


@router.get("/fx/rates")
def fx_rates(currency: str, date_: date = Query(alias="date"), rule: str = "pl_tax_prev_business_day",
             c: psycopg.Connection = Depends(conn)):
    """The NBP table A rate stored by role 2's connector (#34); the demo-day stand-in while no table is stored."""
    found = rate_on(c, currency, date_, rule) or stand_ins.fx_rate(currency.upper(), date_, rule)
    if found is None:
        raise ApiError(404, "not_found", f"No rate for {currency} on {date_}")
    return found


@router.get("/fx/exposure")
def fx_exposure(company: str = Depends(company_id), c: psycopg.Connection = Depends(conn)):
    """FX Shield (#47): role 4's engine (engine.fx_exposure); the fixture-shaped stand-in while it is not importable."""
    engine = finance_engine()
    if engine is not None and hasattr(engine, "fx_exposure"):
        return engine.fx_exposure(c, company)
    return {"items": stand_ins.FX_EXPOSURE.get(company, [])}
