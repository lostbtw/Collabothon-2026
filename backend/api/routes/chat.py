"""POST /chat: the owner's question, answered by the chat agent with evidence; /chat/transcribe turns speech into that question."""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile

from backend.agents import chat as chat_agent
from backend.api import speech
from backend.api.deps import ApiError, conn
from backend.db.seed import companies

router = APIRouter()

MAX_AUDIO_BYTES = 5 * 1024 * 1024
LANGUAGES = ("pl", "en", "ru")


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


@router.post("/chat/transcribe")
async def transcribe(request: Request, file: UploadFile = File(...), language: str = Form(...)):
    if language not in LANGUAGES:
        raise ApiError(422, "invalid_request", "language must be one of pl, en, ru")
    content_type = file.content_type or ""
    if not content_type.startswith("audio/"):
        raise ApiError(415, "unsupported_media_type", "The file is not audio")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        raise ApiError(413, "too_large", "The recording is over 5 MB")
    if not audio:
        raise ApiError(422, "invalid_request", "The recording is empty")
    try:
        return await speech.transcribe(audio, file.filename or "recording", content_type, language,
                                       request.app.state.speech_transport)
    except speech.SpeechUnavailable as error:
        raise ApiError(503, "speech_unavailable", str(error)) from None
