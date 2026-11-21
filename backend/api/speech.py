"""Speech to text for the chat's voice input: Whisper on the team's cluster. Audio and text are never stored or logged."""
import time
from typing import Any

import httpx

from backend import settings

TIMEOUT_SECONDS = 60.0
HEALTH_TIMEOUT_SECONDS = 2.0


class SpeechUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(settings.whisper_url() and settings.whisper_model())


def _base() -> str:
    return settings.whisper_url().rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.whisper_api_key()}"}


async def transcribe(audio: bytes, filename: str, content_type: str, language: str,
                     transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    if not configured():
        raise SpeechUnavailable("Speech to text is not set up (no ORDO_WHISPER_URL)")
    model = settings.whisper_model()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS, headers=_headers()) as client:
            response = await client.post(
                f"{_base()}/audio/transcriptions",
                files={"file": (filename, audio, content_type)},
                data={"model": model, "language": language, "response_format": "verbose_json", "temperature": "0"})
    except httpx.HTTPError as error:
        raise SpeechUnavailable(f"Speech to text did not answer ({type(error).__name__})") from None
    if response.status_code != 200:
        raise SpeechUnavailable(f"Speech to text answered HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise SpeechUnavailable("Speech to text answered without JSON") from None
    return {
        "text": (body.get("text") or "").strip(),
        "language": language,
        "duration_seconds": round(float(body.get("duration") or 0), 2),
        "model": model,
        "seconds": round(time.monotonic() - started, 2),
    }


def reachable(transport: httpx.BaseTransport | None = None) -> bool:
    try:
        with httpx.Client(transport=transport, timeout=HEALTH_TIMEOUT_SECONDS, headers=_headers()) as client:
            return client.get(f"{_base().removesuffix('/v1')}/health").status_code == 200
    except httpx.HTTPError:
        return False
