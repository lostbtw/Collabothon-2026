"""The chat's tools as an MCP server (5.7b), so any MCP client (and OGX later, as configuration) can use them.

Run: `uv run python -m backend.agents.mcp_server [--http PORT]` (stdio by default) against ORDO_DATABASE_URL.
Every tool takes `company_id` first; the other arguments are those of the chat tool. Same functions, same rules:
read-only, plus add_forecast_event (the owner's own statement) and request_action (an inbox card, never a payment).
"""
import argparse
import inspect
import typing
from collections.abc import Callable
from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer

from backend.agents.chat import CHAT_TOOLS
from backend.settings import database_url as default_database_url


def _as_mcp_tool(fn: Callable[..., Any], database_url: str) -> Callable[..., Any]:
    """fn(conn, company, **kw) -> tool(company_id, **kw) that opens its own connection."""
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn) if getattr(fn, "__annotations__", None) else {}
    params = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in list(signature.parameters.values())[2:]]

    def tool(company_id: str, **arguments: Any) -> dict[str, Any]:
        with psycopg.connect(database_url) as conn:
            return fn(conn, company_id, **arguments)

    tool.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[inspect.Parameter("company_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str), *params],
        return_annotation=dict[str, Any])
    tool.__annotations__ = {"company_id": str, **{p.name: p.annotation for p in params
                                                  if p.annotation is not inspect.Parameter.empty},
                            "return": dict[str, Any]}
    return tool


def build_server(database_url: str | None = None) -> MCPServer:
    url = database_url or default_database_url()
    server = MCPServer("ordo", instructions="Read-only finance tools of one Ordo company. Pass company_id "
                                            "(co_borsuk or co_amalfi). No tool moves money.")
    for name, (schema, fn) in CHAT_TOOLS.items():
        server.add_tool(_as_mcp_tool(fn, url), name=name, description=schema["function"]["description"])
    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.agents.mcp_server")
    parser.add_argument("--http", type=int, metavar="PORT", help="serve Streamable HTTP on this port instead of stdio")
    args = parser.parse_args()
    server = build_server()
    if args.http:
        server.run(transport="streamable-http", host="0.0.0.0", port=args.http)
    else:
        server.run()


if __name__ == "__main__":
    main()
