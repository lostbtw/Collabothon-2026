"""The agents' tool loop: openai SDK against the cluster's vLLM. Any failure returns None -> caller's template."""
import json
import logging
import os
import re
import time
from typing import Any

import psycopg
from jsonschema import Draft202012Validator

from backend import settings
from backend.agents import ogx
from backend.agents.tools import Tool

log = logging.getLogger("ordo.agents.llm")
MAX_TOOL_CALLS = 6


def default_client():
    """Client of the cluster's vLLM, never a hosted API; None when ORDO_LLM_ENABLED=0."""
    if os.environ.get("ORDO_LLM_ENABLED", "1") == "0":
        return None
    from openai import DefaultHttpx2Client, OpenAI

    return OpenAI(base_url=settings.llm_base_url(), api_key=settings.llm_token(),
                  timeout=float(os.environ.get("ORDO_LLM_TIMEOUT_SECONDS", "60")), max_retries=0,
                  http_client=DefaultHttpx2Client(verify=settings.llm_verify()))


def _json(content: str | None) -> Any:
    if not content:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(text)


def run_tool_loop(client: Any, conn: psycopg.Connection, company: str, messages: list[dict[str, Any]],
                  tools: dict[str, Tool], final_schema: dict[str, Any], *, max_calls: int = MAX_TOOL_CALLS,
                  trace: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any] | None, list[Any]]:
    """Returns (final JSON or None, every tool result). `trace` collects {tool, arguments, duration_ms}."""
    if ogx.enabled():  # on the cluster OGX runs the loop and calls the same tools over MCP
        outcome = ogx.run(company, messages, sorted(tools), final_schema, max_calls=max_calls, trace=trace)
        if outcome is not None:
            return outcome
    results: list[Any] = []
    calls = 0
    retried = False
    validator = Draft202012Validator(final_schema)
    try:
        while True:
            response = client.chat.completions.create(
                model=settings.llm_model(), messages=messages, tools=[schema for schema, _ in tools.values()],
                tool_choice="auto", temperature=0.2)
            message = response.choices[0].message
            if not message.tool_calls:
                try:
                    answer = _json(message.content)
                except ValueError:
                    answer = None
                problems = ["the answer is not JSON"] if answer is None else [
                    f"{'/'.join(map(str, e.absolute_path)) or 'answer'}: {e.message}" for e in validator.iter_errors(answer)]
                if not problems:
                    return answer, results
                if retried:
                    log.warning("model answer does not match the schema: %s", "; ".join(problems)[:300])
                    return None, results
                retried = True  # one corrective turn: tell the model what is wrong
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": "Your answer does not match the required JSON: "
                                 + "; ".join(problems)[:500] + ". Answer again with JSON only."})
                continue
            messages.append({"role": "assistant", "content": message.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in message.tool_calls]})
            for call in message.tool_calls:
                if calls >= max_calls:
                    log.warning("tool loop stopped after %d calls", calls)
                    return None, results
                calls += 1
                name = call.function.name
                started = time.monotonic()
                if name not in tools:
                    result: Any = {"error": f"unknown tool {name}; use one of {sorted(tools)}"}
                else:
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                        result = tools[name][1](conn, company, **arguments)
                    except Exception as exc:  # wrong arguments: tell the model, let it recover
                        arguments = {}
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                results.append(result)
                if trace is not None:
                    trace.append({"tool": name, "arguments": arguments if name in tools else {},
                                  "duration_ms": int((time.monotonic() - started) * 1000)})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
    except Exception as exc:
        log.warning("model loop failed: %s", exc)
        return None, results
