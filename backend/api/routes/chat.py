"""POST /chat. Stand-in until 5.7: answers from the latest forecast with evidence, no model call."""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends

from backend.api.deps import ApiError, conn, new_id
from backend.api.routes.forecast import latest_forecast
from backend.db.seed import companies
from backend.db.store import Store

router = APIRouter()


@router.post("/chat")
def chat(body: dict[str, Any] = Body(...), c: psycopg.Connection = Depends(conn)):
    if not body.get("message"):
        raise ApiError(422, "invalid_request", "message is required")
    company = body.get("company_id") or companies(c)[0]["id"]
    forecast = latest_forecast(Store(c), company)
    low = forecast["min_balance"]
    return {
        "session_id": body.get("session_id") or new_id("chat"),
        "answer": f"The forecast's lowest balance is {low['amount']['amount']} {low['amount']['currency']} on {low['date']}.",
        "evidence": [{"kind": "forecast", "id": forecast["id"], "label": "Latest forecast", "url": f"/forecast/{forecast['id']}"}],
        "tool_calls": [{"tool": "get_forecast", "arguments": {"company_id": company}, "duration_ms": 0}],
        "created_recommendation_id": None,
        "guardrail": None,
        "trace_id": None,
    }
