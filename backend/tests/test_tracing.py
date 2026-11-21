import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend import tracing

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def tracing_off(monkeypatch):
    monkeypatch.setattr(tracing, "_enabled", False)


def test_without_a_tracking_uri_tracing_stays_off_and_every_helper_is_a_no_op(monkeypatch):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)

    assert tracing.setup("ordo-extraction") is False
    assert tracing.enabled() is False
    with tracing.span("extract_document", {"content_type": "image/jpeg"}) as current:
        tracing.outputs(current, {"status": "ok"})
        tracing.tag(raw_item_id="raw_1")
        assert current is None
        assert tracing.trace_id() is None


def test_an_unreachable_server_turns_tracing_off_within_seconds_without_raising():
    script = textwrap.dedent("""
        import time
        from backend import tracing
        started = time.monotonic()
        print(tracing.setup("ordo-extraction"), tracing.trace_id(), round(time.monotonic() - started))
    """)
    env = {**os.environ, "MLFLOW_TRACKING_URI": "http://127.0.0.1:9"}
    env.pop("MLFLOW_HTTP_REQUEST_MAX_RETRIES", None)
    env.pop("MLFLOW_HTTP_REQUEST_TIMEOUT", None)

    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)

    assert result.returncode == 0, result.stderr
    enabled, trace_id, seconds = result.stdout.split()
    assert (enabled, trace_id) == ("False", "None")
    assert int(seconds) < 30


class FakeMlflow(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def _answer(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        FakeMlflow.requests.append({"method": self.command, "path": self.path,
                                    "workspace": self.headers.get("X-MLFLOW-WORKSPACE"),
                                    "authorization": self.headers.get("Authorization")})

    def do_GET(self):
        self._record()
        if self.path.startswith("/api/3.0/mlflow/server-info"):
            self._answer({"workspaces_enabled": True})
        elif "experiments/get-by-name" in self.path:
            self._answer({"experiment": {"experiment_id": "2", "name": "ordo-extraction",
                                         "artifact_location": "mlflow-artifacts:/2", "lifecycle_stage": "active"}})
        else:
            self._answer({})

    def do_POST(self):
        self._record()
        self._answer({})

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_mlflow():
    FakeMlflow.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMlflow)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_with_a_server_nested_spans_and_model_calls_share_one_trace_sent_to_the_workspace(fake_mlflow):
    script = textwrap.dedent("""
        import json
        import httpx2
        from openai import DefaultHttpx2Client, OpenAI
        from backend import tracing

        answer = {"id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-oss-20b",
                  "choices": [{"index": 0, "finish_reason": "stop",
                               "message": {"role": "assistant", "content": "{}"}}],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=answer))
        client = OpenAI(base_url="https://model.invalid/v1", api_key="x", max_retries=0,
                        http_client=DefaultHttpx2Client(transport=transport))

        on = tracing.setup("ordo-extraction")
        with tracing.span("raw_item.extract", {"raw_item_id": "raw_1"}) as root:
            tracing.tag(raw_item_id="raw_1", company_id="co_sample", missing=None)
            with tracing.span("extract_document"):
                inner = tracing.trace_id()
                client.chat.completions.create(model="gpt-oss-20b", messages=[{"role": "user", "content": "hi"}])
            tracing.outputs(root, {"status": "extracted"})
            outer = tracing.trace_id()
        import mlflow
        print(json.dumps({"on": on, "outer": outer, "inner": inner,
                          "last": mlflow.get_last_active_trace_id(), "after": tracing.trace_id()}))
    """)
    env = {**os.environ, "MLFLOW_TRACKING_URI": fake_mlflow, "MLFLOW_WORKSPACE": "cfo-ai",
           "MLFLOW_TRACKING_TOKEN": "token-for-test", "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING": "false"}

    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen["on"] is True, result.stderr
    assert seen["outer"].startswith("tr-")
    assert seen["inner"] == seen["outer"] == seen["last"]
    assert seen["after"] is None
    deadline = time.monotonic() + 10
    while not any("/traces" in r["path"] and r["method"] == "POST" for r in FakeMlflow.requests):
        assert time.monotonic() < deadline, FakeMlflow.requests
        time.sleep(0.1)
    for request in FakeMlflow.requests:
        assert request["workspace"] == "cfo-ai"
        assert request["authorization"] == "Bearer token-for-test"
