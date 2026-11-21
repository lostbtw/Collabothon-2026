"""NeMo Guardrails in front of the chat: masks IBANs, card numbers and tax ids and refuses off-topic messages."""
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend import settings, tracing

log = logging.getLogger("ordo.agents.guardrails")

KINDS = {"IBAN_CODE": "IBAN", "CREDIT_CARD": "card number", "TAX_ID": "tax id"}
MASKED = re.compile(r"<(" + "|".join(KINDS) + r")>")
REFUSAL = ("I can only help with your company's money: cash, the forecast, costs, clients, invoices and the cards in "
           "your inbox. I do not give investment advice.")

# The server's patterns (deploy/guardrails/), for when it does not answer; longest first so an IBAN stays whole.
LOCAL_PATTERNS = [
    ("IBAN_CODE", re.compile(r"\b[A-Z]{2} ?\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("IBAN_CODE", re.compile(r"\b\d{2}(?: ?\d{4}){6}\b")),
    ("CREDIT_CARD", re.compile(r"\b\d{4}(?:[ -]?\d{4}){3}\b|\b\d{4}[ -]?\d{6}[ -]?\d{5}\b")),
    ("TAX_ID", re.compile(r"\b(?:PL ?)?(?:\d{3}-?\d{3}-?\d{2}-?\d{2}|\d{3}-\d{2}-\d{2}-\d{3})\b")),
    ("TAX_ID", re.compile(r"\bDE ?\d{9}\b")),
    ("TAX_ID", re.compile(r"\b\d{2,3}/\d{3}/\d{4,5}\b")),
]


def local_mask(text: str) -> str:
    for kind, pattern in LOCAL_PATTERNS:
        text = pattern.sub(f"<{kind}>", text)
    return text


@dataclass(frozen=True)
class Verdict:
    status: str  # off | passed | modified | blocked | unavailable
    text: str  # the only text that may go further: to the model, the history, an inbox card
    rail: str | None = None
    masked: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def model_allowed(self) -> bool:
        return self.status in ("off", "passed", "modified")

    def note(self) -> dict[str, Any] | None:
        if self.blocked:
            return {"blocked": True, "reason": REFUSAL}
        if self.masked:
            return {"blocked": False, "reason": "Hidden from the model: " + ", ".join(self.masked)}
        return None


def _verdict(status: str, text: str, rail: str | None = None) -> Verdict:
    return Verdict(status, text, rail, list(dict.fromkeys(KINDS[k] for k in MASKED.findall(text))))


_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(verify=settings.llm_verify(), timeout=httpx.Timeout(
            float(os.environ.get("ORDO_GUARDRAILS_TIMEOUT_SECONDS", "15")), connect=5))
    return _client


def check(message: str, *, http: httpx.Client | None = None, **tags: Any) -> Verdict:
    """Never raises; without an answer the model is not allowed. The trace holds the masked text only."""
    if not settings.guardrails_url():
        return Verdict("off", message)
    with tracing.span("chat.guardrails") as step:
        tracing.tag(**tags)
        verdict = _ask(message, http)
        tracing.tag(guardrails=verdict.status)
        tracing.outputs(step, {"status": verdict.status, "rail": verdict.rail, "masked": verdict.masked,
                               "message": verdict.text})
    return verdict


def _ask(message: str, http: httpx.Client | None) -> Verdict:
    try:
        response = (http or client()).post(
            f"{settings.guardrails_url().rstrip('/')}/v1/checks",
            headers={"Authorization": f"Bearer {settings.guardrails_token()}"},
            json={"model": settings.llm_model(), "messages": [{"role": "user", "content": message}],
                  "guardrails": {"config_id": settings.guardrails_config()}})
        response.raise_for_status()
        body = response.json()
        status, content = body.get("status"), body.get("content")
    except Exception as exc:
        log.warning("guardrails did not answer, the chat answers without the model: %s: %s", type(exc).__name__, exc)
        return _verdict("unavailable", local_mask(message))
    if status == "passed":
        return Verdict("passed", message)
    if status == "modified" and isinstance(content, str) and content.strip():
        return _verdict("modified", content)
    if status == "blocked":  # content is the server's refusal, not the message
        return _verdict("blocked", local_mask(message), body.get("rail"))
    log.warning("guardrails answered %r, the chat answers without the model", status)
    return _verdict("unavailable", local_mask(message))
