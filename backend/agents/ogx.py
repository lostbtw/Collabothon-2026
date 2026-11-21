"""With ORDO_OGX_URL/ORDO_MCP_URL set, OGX (on the cluster) runs the agents' tool loop over MCP instead of llm.py."""
import functools
import json
import logging
import os
from typing import Any

from jsonschema import Draft202012Validator

from backend import settings

log = logging.getLogger("ordo.agents.ogx")
SERVER_LABEL = "ordo"
VIA = "ogx+mcp"


def enabled() -> bool:
    return bool(settings.ogx_url() and settings.mcp_url())


@functools.lru_cache(maxsize=1)
def default_client() -> Any:
    from openai import DefaultHttpx2Client, OpenAI

    return OpenAI(base_url=settings.ogx_url(), api_key=settings.ogx_token(),
                  timeout=float(os.environ.get("ORDO_OGX_TIMEOUT_SECONDS", "90")), max_retries=0,
                  http_client=DefaultHttpx2Client(verify=settings.llm_verify()))


@functools.lru_cache(maxsize=4)
def _discovered_model(client: Any, served: str) -> str:
    """OGX names a model '<provider>/<model>'; find the one that serves our model."""
    ids = [m.id for m in client.models.list()]
    return next((i for i in ids if i == served), None) or next((i for i in ids if i.endswith("/" + served)), served)


def model_id(client: Any) -> str:
    return settings.ogx_model() or _discovered_model(client, settings.llm_model())


def _parse(text: str | None) -> Any:
    """JSON from the model's text: also inside a code fence, with raw line breaks in strings, or after a few words."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1]):
        try:
            return json.loads(candidate, strict=False)
        except ValueError:
            continue
    return None


def _result(item: Any) -> Any:
    if getattr(item, "error", None):
        return {"error": str(item.error)}
    parsed = _parse(getattr(item, "output", None))
    return parsed if parsed is not None else {"text": getattr(item, "output", None) or ""}


AGAIN = ('Your answer was empty or not the required JSON. Answer now from the tool results you already have, '
         'with JSON only.')


def request(company: str, messages: list[dict[str, Any]], tool_names: list[str], final_schema: dict[str, Any], *,
            max_calls: int, client: Any, after: Any = None) -> Any:
    """One Responses call limited to `tool_names`; `after` continues a previous response."""
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
    return client.responses.create(
        model=model_id(client),
        instructions=f'{system} Every tool takes company_id: always pass "{company}".',
        input=[{"role": "user", "content": AGAIN}] if after is not None else turns,
        tools=[{"type": "mcp", "server_label": SERVER_LABEL, "server_url": settings.mcp_url(),
                "require_approval": "never", "allowed_tools": tool_names}],
        text={"format": {"type": "json_schema", "name": "final_answer", "schema": final_schema, "strict": False}},
        max_tool_calls=max_calls, temperature=0.2,
        **({"previous_response_id": after.id} if after is not None else {}))


def _tool_calls(response: Any, company: str, tool_names: list[str]) -> tuple[list[Any], list[dict[str, Any]]] | None:
    """(results, trace entries) of the tools OGX called; None when one was called outside the company or the agent."""
    results: list[Any] = []
    calls: list[dict[str, Any]] = []
    for item in response.output:
        if getattr(item, "type", None) != "mcp_call":
            continue
        arguments = _parse(item.arguments) or {}
        if arguments.get("company_id") != company or item.name not in tool_names:
            log.warning("OGX run dropped: tool %s was called outside %s", item.name, company)
            return None
        results.append(_result(item))
        calls.append({"tool": item.name, "arguments": {k: v for k, v in arguments.items() if k != "company_id"},
                      "duration_ms": 0, "via": VIA})
    return results, calls


def _problems(answer: Any, final_schema: dict[str, Any]) -> list[str]:
    if answer is None:
        return ["the answer is empty or not JSON"]
    return [e.message for e in Draft202012Validator(final_schema).iter_errors(answer)]


def run(company: str, messages: list[dict[str, Any]], tool_names: list[str], final_schema: dict[str, Any], *,
        max_calls: int, trace: list[dict[str, Any]] | None = None,
        client: Any = None) -> tuple[dict[str, Any] | None, list[Any]] | None:
    """Like `llm.run_tool_loop`; None if OGX is unreachable."""
    client = client or default_client()
    try:
        response = request(company, messages, tool_names, final_schema, max_calls=max_calls, client=client)
    except Exception as exc:
        log.warning("OGX did not answer, using the in-process loop: %s", exc)
        return None

    results: list[Any] = []
    calls: list[dict[str, Any]] = []
    answer = None
    for attempt in (1, 2):
        called = _tool_calls(response, company, tool_names)
        if called is None:
            return None, []
        results += called[0]
        calls += called[1]
        answer = _parse(response.output_text)
        problems = _problems(answer, final_schema)
        if not problems:
            break
        log.warning("OGX answer %d does not match the schema: %s | %r", attempt, "; ".join(problems)[:300],
                    (response.output_text or "")[:200])
        answer = None
        if attempt == 2:
            break
        try:  # one corrective turn, as in the in-process loop: the model sometimes ends without its final text
            response = request(company, messages, tool_names, final_schema, max_calls=2, client=client, after=response)
        except Exception as exc:
            log.warning("OGX did not answer the corrective turn: %s", exc)
            break
    if trace is not None:
        trace.extend(calls)
    if answer is not None:
        log.info("OGX ran %d tool call(s) over MCP: %s", len(calls), ", ".join(c["tool"] for c in calls))
    return answer, results


def main(argv: list[str] | None = None) -> int:
    """Cluster check: `python -m backend.agents.ogx "question" [company]`; exit 1 unless a tool was called."""
    import sys

    from backend.agents.chat import CHAT_TOOLS, FINAL_SCHEMA, SYSTEM

    args = list(sys.argv[1:] if argv is None else argv)
    question = args[0] if args else "How much cash do I have?"
    company = args[1] if len(args) > 1 else "co_borsuk"
    if not enabled():
        print("OGX is off: set ORDO_OGX_URL and ORDO_MCP_URL")
        return 1
    client = default_client()
    print(f"OGX {settings.ogx_url()} · model {model_id(client)} · MCP server {settings.mcp_url()}")
    trace: list[dict[str, Any]] = []
    outcome = run(company, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                  sorted(CHAT_TOOLS), FINAL_SCHEMA, max_calls=6, trace=trace, client=client)
    if outcome is None:
        print("OGX did not answer")
        return 1
    answer, _ = outcome
    for call in trace:
        print(f"tool over MCP: {call['tool']} {json.dumps(call['arguments'])}")
    print(f"answer: {answer['answer'] if answer else '(not usable: the agent would fall back to its template)'}")
    return 0 if trace and answer else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    raise SystemExit(main())
