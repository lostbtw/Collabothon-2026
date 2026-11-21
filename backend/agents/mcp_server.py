"""The agents' tools over MCP for OGX: `python -m backend mcp [--http PORT]`. Read-only, plus two owner-safe writes."""
import argparse
import inspect
import logging
import typing
from collections.abc import Callable
from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend import settings
from backend.agents import fx, model_passthrough
from backend.agents.chat import CHAT_TOOLS
from backend.agents.tools import LIQUIDITY_TOOLS, Tool
from backend.settings import database_url as default_database_url

DEFAULT_PORT = 8000
log = logging.getLogger("ordo.agents.mcp")


def all_tools() -> dict[str, Tool]:
    return {**CHAT_TOOLS, **LIQUIDITY_TOOLS, **fx.TOOLS}


def _as_mcp_tool(fn: Callable[..., Any], database_url: str) -> Callable[..., Any]:
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn) if getattr(fn, "__annotations__", None) else {}
    params = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in list(signature.parameters.values())[2:]]

    def tool(company_id: str, **arguments: Any) -> dict[str, Any]:
        try:
            with psycopg.connect(database_url) as conn:
                return fn(conn, company_id, **arguments)
        except Exception as exc:
            log.warning("tool %s failed: %s", getattr(fn, "__name__", "?"), exc)
            return {"error": f"{type(exc).__name__}: {exc}"}

    tool.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[inspect.Parameter("company_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str), *params],
        return_annotation=dict[str, Any])
    tool.__annotations__ = {"company_id": str, **{p.name: p.annotation for p in params
                                                  if p.annotation is not inspect.Parameter.empty},
                            "return": dict[str, Any]}
    return tool


def build_server(database_url: str | None = None) -> MCPServer:
    url = database_url or default_database_url()
    server = MCPServer("ordo", instructions="Finance tools of one Ordo company. Pass company_id "
                                            "(co_borsuk or co_amalfi). No tool moves money.")
    for name, (schema, fn) in all_tools().items():
        server.add_tool(_as_mcp_tool(fn, url), name=name, description=schema["function"]["description"])

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "tools": sorted(all_tools())})

    server.custom_route(model_passthrough.PREFIX + "/{path:path}", methods=["GET", "POST"])(model_passthrough.forward)

    return server


def transport_security() -> TransportSecuritySettings:
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *settings.mcp_allowed_hosts()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend mcp")
    parser.add_argument("--http", type=int, metavar="PORT", nargs="?", const=DEFAULT_PORT,
                        help=f"serve Streamable HTTP on this port (default {DEFAULT_PORT}) instead of stdio")
    args = parser.parse_args(argv)
    server = build_server()
    if args.http:
        # Stateless with JSON answers: each tool call is one plain HTTP request, so OGX needs no session.
        server.run(transport="streamable-http", host="0.0.0.0", port=args.http, stateless_http=True, json_response=True,
                   transport_security=transport_security())
    else:
        server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
