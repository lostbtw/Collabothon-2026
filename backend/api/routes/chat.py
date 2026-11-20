"""POST /chat: the owner's question, answered by the chat agent (backend/agents/chat.py) with evidence."""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends, Request

from backend.agents import chat as chat_agent
from backend.api.deps import ApiError, conn
from backend.db.seed import companies

router = APIRouter()


@router.post("/chat")
def chat(request: Request, body: dict[str, Any] = Body(...), c: psycopg.Connection = Depends(conn)):
    message = (body.get("message") or "").strip()
    if not message:
        raise ApiError(422, "invalid_request", "message is required")
    known = [co["id"] for co in companies(c)]
    company = body.get("company_id") or known[0]
    if company not in known:
        raise ApiError(404, "not_found", f"No company with id {company!r}")
    return chat_agent.answer(c, company, message, body.get("session_id"), request.app.state.chat_model())
