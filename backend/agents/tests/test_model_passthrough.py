"""OGX's way to the model: everything passes through, and a tool result made of text parts becomes plain text."""
import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.agents import model_passthrough
from backend.agents.model_passthrough import text_parts_to_text


def test_a_tool_result_of_text_parts_becomes_plain_text():
    body = {"messages": [
        {"role": "user", "content": "How much cash?"},
        {"role": "tool", "tool_call_id": "c1", "content": [{"type": "text", "text": '{"total": "5"}'}, {"type": "text", "text": "ok"}]},
        {"role": "user", "content": [{"type": "text", "text": "and this"}, {"type": "image_url", "image_url": {"url": "x"}}]},
    ]}

    assert text_parts_to_text(body) == 1
    assert body["messages"][1]["content"] == '{"total": "5"}\nok'
    assert isinstance(body["messages"][2]["content"], list)


@pytest.fixture
def model(monkeypatch):
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-oss-20b"}]})
        if json.loads(request.content).get("stream"):
            return httpx.Response(200, stream=httpx.ByteStream(b'data: {"a": 1}\n\ndata: [DONE]\n\n'),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setenv("ORDO_LLM_BASE_URL", "https://model.test/v1")
    monkeypatch.setattr(model_passthrough, "_client", httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    app = Starlette(routes=[Route(model_passthrough.PREFIX + "/{path:path}", model_passthrough.forward, methods=["GET", "POST"])])
    with TestClient(app) as client:
        yield client, seen


def test_requests_reach_the_model_with_the_callers_token_and_plain_tool_text(model):
    client, seen = model
    body = {"model": "gpt-oss-20b", "messages": [{"role": "tool", "tool_call_id": "c1", "content": [{"type": "text", "text": "42"}]}]}

    answer = client.post("/model/v1/chat/completions", json=body, headers={"Authorization": "Bearer t0ken"})

    assert answer.json() == {"choices": [{"message": {"content": "hi"}}]}
    assert str(seen[0].url) == "https://model.test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer t0ken"
    assert json.loads(seen[0].content)["messages"][0]["content"] == "42"
    assert client.get("/model/v1/models").json()["data"][0]["id"] == "gpt-oss-20b"


def test_a_streamed_answer_is_passed_on_as_it_comes(model):
    client, _ = model

    answer = client.post("/model/v1/chat/completions", json={"model": "gpt-oss-20b", "stream": True, "messages": []})

    assert answer.headers["content-type"].startswith("text/event-stream")
    assert answer.text == 'data: {"a": 1}\n\ndata: [DONE]\n\n'
