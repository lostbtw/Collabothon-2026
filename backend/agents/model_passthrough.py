"""The way OGX reaches the model: a pass-through to the cluster's vLLM endpoint that changes one thing.

OGX hands a tool's result back to the model as a list of text parts; the gpt-oss chat handler of our vLLM accepts
only plain text there and answers 400. So a message whose content is only text parts becomes one string. Everything
else (path, body, token, streaming) goes through untouched. Served by the ordo-mcp process at /model/v1/...
"""
import json
import logging
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from backend import settings

log = logging.getLogger("ordo.agents.model_passthrough")
PREFIX = "/model/v1"
FORWARDED = ("authorization", "content-type", "accept")
_client: httpx.AsyncClient | None = None


def text_parts_to_text(body: dict[str, Any]) -> int:
    """Turns every message content made only of text parts into plain text. Returns how many were changed."""
    changed = 0
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list) and content and all(isinstance(p, dict) and p.get("type") == "text" for p in content):
            message["content"] = "\n".join(p.get("text", "") for p in content)
            changed += 1
    return changed


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(verify=settings.llm_verify(), timeout=httpx.Timeout(120, connect=10))
    return _client


async def forward(request: Request) -> Response:
    raw = await request.body()
    stream = False
    if raw and "json" in request.headers.get("content-type", ""):
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if isinstance(body, dict):
            stream = bool(body.get("stream"))
            if text_parts_to_text(body):
                raw = json.dumps(body).encode()
    upstream = client().build_request(
        request.method, f"{settings.llm_base_url().rstrip('/')}/{request.path_params['path']}", content=raw,
        params=request.query_params, headers={k: v for k, v in request.headers.items() if k.lower() in FORWARDED})
    answer = await client().send(upstream, stream=True)
    if answer.status_code >= 400:
        log.warning("model answered %d to %s", answer.status_code, request.path_params["path"])
    if not stream:
        data = await answer.aread()
        await answer.aclose()
        return Response(data, status_code=answer.status_code, media_type=answer.headers.get("content-type"))

    async def chunks():
        try:
            async for chunk in answer.aiter_raw():
                yield chunk
        finally:
            await answer.aclose()

    return StreamingResponse(chunks(), status_code=answer.status_code, media_type=answer.headers.get("content-type"))
