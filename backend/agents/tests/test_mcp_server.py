"""Seam: the MCP server. An MCP client lists and calls the same tools the agents use (5.7b, OGX orchestration)."""
import anyio
from mcp import Client

from backend.agents.mcp_server import all_tools, build_server, transport_security
from backend.db.fixtures import load_fixtures


def test_an_mcp_client_lists_and_calls_the_tools(db, db_url):
    load_fixtures(db)
    server = build_server(database_url=db_url)

    async def scenario():
        async with Client(server) as client:
            listed = await client.list_tools()
            result = await client.call_tool("get_forecast", {"company_id": "co_borsuk"})
            return {t.name for t in listed.tools}, result

    names, result = anyio.run(scenario)

    assert names == set(all_tools())
    assert {"get_cash_position", "run_scenario", "get_fx_case"} <= names  # chat, liquidity agent, FX Shield
    assert not result.is_error
    assert "fc_20261121a" in result.content[0].text


def test_a_failing_tool_tells_the_model_why(db, db_url):
    load_fixtures(db)
    server = build_server(database_url=db_url)

    async def scenario():
        async with Client(server) as client:
            return await client.call_tool("explain_recommendation", {"company_id": "co_borsuk", "recommendation_id": 7})

    result = anyio.run(scenario)

    assert "error" in result.content[0].text


def test_only_localhost_and_the_configured_service_names_are_answered(monkeypatch):
    monkeypatch.setenv("ORDO_MCP_ALLOWED_HOSTS", "ordo-mcp:8000, ordo-mcp.cfo-ai.svc.cluster.local:8000")

    hosts = transport_security().allowed_hosts

    assert "ordo-mcp.cfo-ai.svc.cluster.local:8000" in hosts and "127.0.0.1:*" in hosts
    assert transport_security().enable_dns_rebinding_protection
