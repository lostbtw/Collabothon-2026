"""OGX orchestration: the agents' loop goes through OGX's Responses API, which calls the tools over MCP.
OGX itself runs on the cluster; here a stand-in answers the one call the agents make."""
import json
from types import SimpleNamespace as NS

import pytest

from backend.agents import llm, ogx

SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string", "minLength": 1}}}
MESSAGES = [{"role": "system", "content": "Answer with JSON."}, {"role": "user", "content": "How much cash do I have?"}]


def mcp_call(name: str, arguments: dict, output: dict | None = None, error: str | None = None) -> NS:
    return NS(type="mcp_call", name=name, arguments=json.dumps(arguments), output=json.dumps(output) if output else None, error=error)


class Ogx:
    """What the openai SDK shows of an OGX server: its models and one Responses call."""

    def __init__(self, output: list, text: str, fail: bool = False):
        self.requests: list[dict] = []
        self.models = NS(list=lambda: [NS(id="sentence-transformers/embed"), NS(id="vllm-inference/gpt-oss-20b")])
        self.responses = NS(create=self._create)
        self._answer, self._fail = NS(output=output, output_text=text), fail

    def _create(self, **request):
        self.requests.append(request)
        if self._fail:
            raise ConnectionError("no route to OGX")
        return self._answer


@pytest.fixture
def cluster(monkeypatch):
    monkeypatch.setenv("ORDO_OGX_URL", "http://ordo-ogx-service:8321/v1")
    monkeypatch.setenv("ORDO_MCP_URL", "http://ordo-mcp:8000/mcp")
    monkeypatch.delenv("ORDO_OGX_MODEL", raising=False)
    ogx._discovered_model.cache_clear()


def test_ogx_runs_the_loop_and_the_tools_come_back_as_results(cluster):
    cash = {"total_liquidity_base": {"amount": "84120.55", "currency": "PLN"}}
    server = Ogx([NS(type="mcp_list_tools"), mcp_call("get_cash_position", {"company_id": "co_borsuk"}, cash),
                  NS(type="message")], '{"answer": "You have 84,120.55 PLN."}')
    trace: list = []

    answer, results = ogx.run("co_borsuk", MESSAGES, ["get_cash_position", "get_forecast"], SCHEMA, max_calls=6,
                              trace=trace, client=server)

    assert answer == {"answer": "You have 84,120.55 PLN."}
    assert results == [cash]
    assert trace == [{"tool": "get_cash_position", "arguments": {}, "duration_ms": 0, "via": "ogx+mcp"}]
    request = server.requests[0]
    assert request["model"] == "vllm-inference/gpt-oss-20b"  # found among OGX's models
    assert request["tools"] == [{"type": "mcp", "server_label": "ordo", "server_url": "http://ordo-mcp:8000/mcp",
                                 "require_approval": "never", "allowed_tools": ["get_cash_position", "get_forecast"]}]
    assert '"co_borsuk"' in request["instructions"] and request["input"] == [MESSAGES[1]]
    assert request["text"]["format"]["schema"] == SCHEMA  # OGX is asked for the agent's JSON shape


def test_an_answer_with_words_around_the_json_is_still_read(cluster):
    server = Ogx([mcp_call("get_cash_position", {"company_id": "co_borsuk"}, {"total": "5"})],
                 'Here it is:\n{"answer": "You have 5.\nThat is all."}')

    answer, _ = ogx.run("co_borsuk", MESSAGES, ["get_cash_position"], SCHEMA, max_calls=6, client=server)

    assert answer == {"answer": "You have 5.\nThat is all."}


def test_a_tool_called_for_another_company_drops_the_run(cluster):
    server = Ogx([mcp_call("get_cash_position", {"company_id": "co_amalfi"}, {"total": "1"})], '{"answer": "x"}')

    assert ogx.run("co_borsuk", MESSAGES, ["get_cash_position"], SCHEMA, max_calls=6, client=server) == (None, [])


def test_a_tool_error_reaches_the_results_and_a_bad_answer_is_refused(cluster):
    server = Ogx([mcp_call("search_ledger", {"company_id": "co_borsuk", "month": "13"}, error="bad month")], "not json")

    answer, results = ogx.run("co_borsuk", MESSAGES, ["search_ledger"], SCHEMA, max_calls=6, client=server)

    assert answer is None and results == [{"error": "bad month"}]


def test_the_agents_loop_goes_through_ogx_on_the_cluster(cluster, monkeypatch):
    server = Ogx([mcp_call("get_cash_position", {"company_id": "co_borsuk"}, {"total": "5"})], '{"answer": "5"}')
    monkeypatch.setattr(ogx, "default_client", lambda: server)
    never = NS(chat=None)  # the in-process loop would fail on this client

    answer, results = llm.run_tool_loop(never, None, "co_borsuk", list(MESSAGES), {"get_cash_position": ({}, None)}, SCHEMA)

    assert answer == {"answer": "5"} and results == [{"total": "5"}]


def test_without_ogx_the_agent_runs_its_own_loop(cluster, monkeypatch):
    monkeypatch.setattr(ogx, "default_client", lambda: Ogx([], "", fail=True))
    said = NS(choices=[NS(message=NS(tool_calls=None, content='{"answer": "from the in-process loop"}'))])
    model = NS(chat=NS(completions=NS(create=lambda **_: said)))

    answer, results = llm.run_tool_loop(model, None, "co_borsuk", list(MESSAGES), {}, SCHEMA)

    assert answer == {"answer": "from the in-process loop"} and results == []


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ORDO_OGX_URL", raising=False)
    assert not ogx.enabled()
