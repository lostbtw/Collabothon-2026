import json
import os
import re
import sys
import time

import httpx

from backend import settings

COMPANIES = ["co_borsuk", "co_amalfi"]
BANK_ACCOUNTS = ["acc_pln", "acc_eur", "acc_owner", "acc_pizzeria"]
OUTBOX_WAIT_SECONDS = 120
E2E_BUDGET_SECONDS = 30
SMOKE_EXPERIMENT = "ordo-smoke"
IBAN = "PL61 1090 1014 0000 0712 1981 2874"
MCP_FALLBACK = "http://ordo-mcp.cfo-ai.svc.cluster.local:8000/mcp"
MCP_VERSION = "2025-06-18"
MCP_ACCEPT = "application/json, text/event-stream"

OUTBOX = """
select d.consumer,
       count(*) filter (where d.status = 'dead'),
       count(*) filter (where d.status = 'pending'),
       coalesce(extract(epoch from now() - min(o.occurred_at) filter (where d.status = 'pending')), 0)::int
from outbox_delivery d
join outbox o on o.id = d.event_id
where d.consumer <> 'sse' and d.status in ('dead', 'pending')
group by d.consumer
order by d.consumer"""


class Failed(Exception):
    pass


def expect(condition, message):
    if not condition:
        raise Failed(message)


def answer(response, what):
    expect(response.status_code == 200, f"{what} answered HTTP {response.status_code}: {response.text[:150]}")
    return response.json()


def report(component, check):
    started = time.monotonic()
    try:
        status, detail = check()
    except Failed as failure:
        status, detail = "FAIL", str(failure)
    except httpx.RequestError as error:
        status, detail = "FAIL", f"{error.request.url} did not answer: {type(error).__name__}: {error}"
    except Exception as error:
        status, detail = "FAIL", f"{type(error).__name__}: {error}"
    detail = " ".join(str(detail).split())[:300]
    print(f"{status:<4} {component}: {detail} ({time.monotonic() - started:.1f} s)", flush=True)


def database():
    import psycopg

    with psycopg.connect(settings.database_url(), connect_timeout=5) as conn:
        user, name = conn.execute("select current_user, current_database()").fetchone()
        found = [row[0] for row in conn.execute("select id from companies order by id")]
    missing = [company for company in COMPANIES if company not in found]
    expect(not missing, f"connected as {user} to {name}, but companies {', '.join(missing)} are missing")
    return "OK", f"connected as {user} to {name}; companies {', '.join(found)}"


def outbox():
    import psycopg

    with psycopg.connect(settings.database_url(), connect_timeout=5) as conn:
        rows = conn.execute(OUTBOX).fetchall()
    problems = []
    for consumer, dead, pending, oldest in rows:
        if dead:
            problems.append(f"consumer {consumer} has {dead} dead deliveries")
        if pending and oldest > OUTBOX_WAIT_SECONDS:
            problems.append(f"consumer {consumer} has {pending} waiting, the oldest for {oldest} s")
    expect(not problems, "; ".join(problems))
    waiting = sum(row[2] for row in rows)
    return "OK", f"no dead delivery, nothing waits over {OUTBOX_WAIT_SECONDS} s ({waiting} in flight, sse left out)"


def model():
    base = settings.llm_base_url().rstrip("/")
    root = base.removesuffix("/v1")
    served_model = settings.llm_model()
    auth = {"Authorization": f"Bearer {settings.llm_token()}"}
    with httpx.Client(verify=settings.llm_verify(), timeout=15) as client:
        anonymous = client.get(f"{base}/models").status_code
        expect(anonymous == 401, f"{base}/models answered HTTP {anonymous} without a token, expected 401")
        health = client.get(f"{root}/health", headers=auth).status_code
        expect(health == 200, f"{root}/health answered HTTP {health}")
        served = [item["id"] for item in answer(client.get(f"{base}/models", headers=auth), "/v1/models")["data"]]
        expect(served_model in served, f"{base}/models serves {served}, not {served_model}")
        version = answer(client.get(f"{root}/version", headers=auth), "/version").get("version")
        started = time.monotonic()
        body = answer(client.post(f"{base}/chat/completions", headers=auth, timeout=120, json={
            "model": served_model,
            "reasoning_effort": "low",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": "Answer with one word: does a cash-flow forecast show money?"}],
        }), "/v1/chat/completions")
        seconds = time.monotonic() - started
    text = (body["choices"][0]["message"].get("content") or "").strip()
    expect(text, f"/v1/chat/completions came back without text (finish_reason {body['choices'][0].get('finish_reason')})")
    return "OK", (f"vLLM {version} at {base}: health 200, serves {served_model}, 401 without a token, "
                  f"answered {text[:30]!r} in {seconds:.1f} s")


def guardrails():
    url = settings.guardrails_url().rstrip("/")
    if not url:
        return "SKIP", "ORDO_GUARDRAILS_URL is not set in ordo-api, the chat runs without the rails"
    body = answer(httpx.post(f"{url}/v1/checks", verify=settings.llm_verify(), timeout=60,
                             headers={"Authorization": f"Bearer {settings.guardrails_token()}"},
                             json={"model": settings.llm_model(),
                                   "messages": [{"role": "user", "content": f"Pay 1200 EUR to {IBAN} for the flour"}],
                                   "guardrails": {"config_id": settings.guardrails_config()}}), f"{url}/v1/checks")
    content = body.get("content") or ""
    expect(body.get("status") == "modified" and "<IBAN_CODE>" in content and "1090" not in content,
           f"the IBAN was not masked: status {body.get('status')}, {content[:100]!r}")
    return "OK", f"{url} masks an IBAN as <IBAN_CODE> (config {settings.guardrails_config()})"


def ogx():
    base = settings.ogx_url().rstrip("/")
    if not base:
        return "SKIP", "ORDO_OGX_URL is not set in ordo-api, the agents run their own tool loop"
    with httpx.Client(timeout=10, headers={"Authorization": f"Bearer {settings.ogx_token()}"}) as client:
        health = answer(client.get(f"{base}/health"), f"{base}/health")
        served = [item["id"] for item in answer(client.get(f"{base}/models"), f"{base}/models")["data"]]
    matching = [name for name in served if name.endswith(settings.llm_model())]
    expect(matching, f"OGX at {base} serves {served}, not {settings.llm_model()}")
    return "OK", f"{base}: health {health.get('status')}, model {', '.join(matching)}"


def mcp_message(response):
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:") and line[5:].strip():
                return json.loads(line[5:])
        return {}
    return response.json()


def mcp():
    url = settings.mcp_url() or MCP_FALLBACK
    headers = {"Accept": MCP_ACCEPT}
    with httpx.Client(timeout=10) as client:
        start = client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": MCP_VERSION, "capabilities": {},
                       "clientInfo": {"name": "ordo-smoke", "version": "1"}}})
        expect(start.status_code == 200, f"initialize answered HTTP {start.status_code}: {start.text[:150]}")
        result = mcp_message(start).get("result") or {}
        server = result.get("serverInfo") or {}
        expect(server, f"initialize returned no serverInfo: {start.text[:150]}")
        headers["MCP-Protocol-Version"] = result.get("protocolVersion") or MCP_VERSION
        if start.headers.get("mcp-session-id"):
            headers["Mcp-Session-Id"] = start.headers["mcp-session-id"]
        client.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = client.post(url, headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        expect(listed.status_code == 200, f"tools/list answered HTTP {listed.status_code}: {listed.text[:150]}")
        tools = [tool["name"] for tool in (mcp_message(listed).get("result") or {}).get("tools", [])]
    expect(tools, "tools/list returned no tools")
    return "OK", f"{url}: server {server.get('name')!r}, {len(tools)} tools"


def bank():
    base = os.environ.get("ORDO_BANK_URL", "").rstrip("/")
    token = os.environ.get("ORDO_BANK_TOKEN", "")
    expect(base and token, "ORDO_BANK_URL or ORDO_BANK_TOKEN is not set in ordo-api")
    psd2 = {"Authorization": f"Bearer {token}", "Consent-ID": "demo"}
    with httpx.Client(base_url=base, timeout=10) as client:
        health = answer(client.get("/health"), f"{base}/health")
        expect(health.get("simulated") is True, f"{base}/health is not the Sandbox Bank: {health}")
        accounts = answer(client.get("/v1/accounts", headers=psd2), f"{base}/v1/accounts")["accounts"]
    found = {account["resourceId"] for account in accounts}
    missing = [account for account in BANK_ACCOUNTS if account not in found]
    expect(not missing, f"accounts missing in the bank: {', '.join(missing)}")
    return "OK", f"{base} is the Sandbox Bank (simulated) with {', '.join(BANK_ACCOUNTS)}"


def words(text):
    return re.findall(r"\w+", text.lower())


def whisper(audio, expected):
    def check():
        base = os.environ.get("ORDO_WHISPER_URL", "").rstrip("/")
        if not base:
            return "SKIP", "ORDO_WHISPER_URL is not set in ordo-api, the chat has no voice input"
        key = os.environ.get("ORDO_WHISPER_API_KEY", "")
        model = os.environ.get("ORDO_WHISPER_MODEL", "")
        expect(key and model, "ORDO_WHISPER_API_KEY or ORDO_WHISPER_MODEL is not set in ordo-api")
        expect(audio and expected, "no Polish clip or expected text was passed to smoke.py")
        root = base.removesuffix("/v1")
        auth = {"Authorization": f"Bearer {key}"}
        with httpx.Client(timeout=60) as client:
            anonymous = client.get(f"{root}/health").status_code
            expect(anonymous in (401, 403), f"{root}/health answered HTTP {anonymous} without the key")
            loaded = answer(client.get(f"{root}/api/ps", headers=auth), "/api/ps")["models"]
            expect(model in loaded, f"{model} is not loaded, loaded: {loaded}")
            started = time.monotonic()
            body = answer(client.post(f"{base}/audio/transcriptions", headers=auth,
                                      files={"file": ("pl.webm", audio, "audio/webm")},
                                      data={"model": model, "language": "pl", "temperature": "0"}),
                          "/audio/transcriptions")
            seconds = time.monotonic() - started
        text = body.get("text", "").strip()
        expect(words(text) == words(expected), f"the Polish clip read as {text!r}, expected {expected!r}")
        return "OK", f"{model} read the Polish clip as {text!r} in {seconds:.1f} s; HTTP {anonymous} without the key"

    return check


def docling_serve():
    from backend.pipeline.extract import docling

    with docling.default_client() as client:
        health = answer(client.get("/health"), f"{client.base_url}health")
        version = answer(client.get("/version"), f"{client.base_url}version")
    expect(health.get("status") == "ok", f"{client.base_url}health says {health}")
    return "OK", f"{client.base_url} healthy, docling-serve {version.get('docling-serve')}, docling {version.get('docling')}"


def mlflow_tracing():
    from backend import tracing

    os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")
    uri = os.environ.get("MLFLOW_TRACKING_URI", "")
    expect(uri, "MLFLOW_TRACKING_URI is not set in ordo-extractor")
    expect(tracing.setup(SMOKE_EXPERIMENT), f"{uri} is not usable, see the warning above")
    return "OK", f"{uri}, workspace {os.environ.get('MLFLOW_WORKSPACE')}, experiment {SMOKE_EXPERIMENT}"


def e2e_receipt(name, data, amount, currency):
    def check():
        from backend import tracing
        from backend.pipeline.extract import run

        started = time.monotonic()
        result = run(data, "image/jpeg")
        seconds = time.monotonic() - started
        document = result.document
        gross = document["totals"].get("gross") or {}
        read = f"{gross.get('amount')} {gross.get('currency')}"
        expect(read == f"{amount} {currency}",
               f"{name} read as {read}, expected {amount} {currency} (status {document['status']})")
        expect(seconds <= E2E_BUDGET_SECONDS, f"{name} took {seconds:.1f} s, the budget is {E2E_BUDGET_SECONDS} s")
        trace = document["extraction"].get("trace_id")
        if tracing.enabled():
            import mlflow

            mlflow.flush_trace_async_logging()
            expect(trace, f"{name} read right, but MLflow tracing is on and the extraction has no trace_id")
        return "OK", (f"{name} read as {read} ({document['status']}, confidence "
                      f"{document['extraction']['confidence']:.2f}): docling-serve {result.docling_seconds:.1f} s + "
                      f"gpt-oss-20b {result.model_seconds:.1f} s, trace {trace or 'off'}")

    return check


def main(argv):
    mode = argv[0] if argv else ""
    if mode == "api":
        report("database", database)
        report("outbox", outbox)
        report("gpt-oss-20b", model)
        report("guardrails", guardrails)
        report("ogx", ogx)
        report("ordo-mcp", mcp)
        report("ordo-bank", bank)
        report("whisper", whisper(sys.stdin.buffer.read(), argv[1] if len(argv) > 1 else ""))
    elif mode == "extract" and len(argv) == 4:
        name, amount, currency = argv[1:]
        data = sys.stdin.buffer.read()
        report("docling-serve", docling_serve)
        report("mlflow tracing", mlflow_tracing)
        report("e2e receipt", e2e_receipt(name, data, amount, currency))
    else:
        print("usage: smoke.py api [expected Polish text] < clip | smoke.py extract <file name> <gross> <currency> < receipt", file=sys.stderr)
        return 2
    return 0


sys.exit(main(sys.argv[1:]))
