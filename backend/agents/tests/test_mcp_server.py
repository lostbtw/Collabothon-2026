"""Seam: the MCP server. An MCP client lists and calls the same tools the chat uses (5.7b)."""
import anyio
from mcp import Client

from backend.agents.chat import CHAT_TOOLS
from backend.agents.mcp_server import build_server
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

    assert names == set(CHAT_TOOLS)
    assert not result.is_error
    assert "fc_20261121a" in result.content[0].text
