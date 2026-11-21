"""The agents' read-only tools: (OpenAI schema, fn(conn, company_id, **args) -> dict), also served over MCP."""
from datetime import date
from decimal import Decimal
from typing import Any, Callable

import psycopg

from backend.agents import stand_ins
from backend.api.ports import finance_engine as _engine, latest_base_forecast
from backend.db.store import Store


latest_forecast = latest_base_forecast


def get_forecast(conn: psycopg.Connection, company: str, forecast_id: str | None = None) -> dict[str, Any]:
    forecast = Store(conn).get("forecast", forecast_id) if forecast_id else latest_forecast(conn, company)
    if forecast is None:
        return {"error": "no forecast yet"}
    engine = _engine()
    stress = engine.stress_case(conn, company) if engine and hasattr(engine, "stress_case") else stand_ins.STRESS.get(company)
    return {
        "forecast_id": forecast["id"],
        "as_of_date": forecast["as_of_date"],
        "horizon_days": forecast.get("horizon_days"),
        "base_currency": forecast["base_currency"],
        "opening_balance": forecast["opening_balance"],
        "safety_buffer": forecast.get("safety_buffer"),
        "min_balance": forecast["min_balance"],
        "first_negative_date": forecast.get("first_negative_date"),
        "alerts": forecast["alerts"],
        "components": [{k: c.get(k) for k in ("id", "label", "kind", "amount_base", "schedule", "dates", "confidence")}
                       for c in forecast["components"]],
        "events": forecast.get("events", []),
        "stress_case": stress,
    }


def list_overdue_receivables(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    """Receivables the forecast expects late, with the client's name when it is a known counterparty."""
    forecast = latest_forecast(conn, company)
    if forecast is None:
        return {"items": []}
    counterparties = Store(conn).list("counterparty", company_id=company)
    items = []
    for c in forecast["components"]:
        if c["kind"] != "known_receivable":
            continue
        client = next((cp["name"].split(" ")[0] for cp in counterparties
                       if cp["name"].split(" ")[0].lower() in c["label"].lower()), None)
        document = next((e["id"] for e in c.get("evidence", []) if e["kind"] == "document"), None)
        items.append({"component_id": c["id"], "client": client, "label": c["label"], "amount_base": c["amount_base"],
                      "expected_date": (c.get("dates") or [None])[0], "schedule": c.get("schedule"), "document_id": document})
    return {"items": items}


def run_scenario(conn: psycopg.Connection, company: str, credit_line_limit: str | None = None,
                 from_date: str | None = None, shift_receivable: dict | None = None,
                 shift_payable: dict | None = None) -> dict[str, Any]:
    """What-if, as POST /forecast/scenario."""
    engine = _engine()
    if engine and hasattr(engine, "scenario"):
        body: dict[str, Any] = {}
        if credit_line_limit:
            body["credit_line"] = {"limit": {"amount": credit_line_limit}, "from": from_date}
        if shift_receivable:
            body["shift_receivable"] = shift_receivable
        if shift_payable:
            body["shift_payable"] = shift_payable
        result = engine.scenario(conn, company, body)
        return {"forecast_id": result["id"], "min_balance": result["min_balance"]}
    if shift_receivable or shift_payable:
        return {"error": "only the credit-line scenario is available until the finance engine lands"}
    forecast = latest_forecast(conn, company)
    if forecast is None:
        return {"error": "no forecast yet"}
    limit = Decimal(credit_line_limit or "0")
    start = from_date or forecast["as_of_date"]
    low = min(((Decimal(p["balance"]) + (limit if p["date"] >= start else 0), p["date"]) for p in forecast["points"]),
              key=lambda x: x[0])
    return {"credit_line_limit": {"amount": f"{limit:.2f}", "currency": forecast["base_currency"]}, "available_from": start,
            "min_balance": {"date": low[1], "amount": {"amount": f"{low[0]:.2f}", "currency": forecast["base_currency"]}}}


def get_bank_price_list(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    return stand_ins.PRICE_LISTS.get(company, {"error": "no price list"})


Tool = tuple[dict[str, Any], Callable[..., dict[str, Any]]]


def _schema(name: str, description: str, properties: dict | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                              "parameters": {"type": "object", "properties": properties or {},
                                                             "additionalProperties": False}}}


LIQUIDITY_TOOLS: dict[str, Tool] = {
    "get_forecast": (_schema("get_forecast", "The latest cash forecast: lowest balance, alerts, components, stress case"),
                     get_forecast),
    "list_overdue_receivables": (_schema("list_overdue_receivables", "Client invoices the forecast expects to be paid late"),
                                 list_overdue_receivables),
    "run_scenario": (_schema("run_scenario", "Lowest balance with a credit line, a receivable moved or a payable delayed",
                             {"credit_line_limit": {"type": "string", "description": "decimal, base currency"},
                              "from_date": {"type": "string", "format": "date"},
                              "shift_receivable": {"type": "object", "description": "{document_id, new_date}"},
                              "shift_payable": {"type": "object", "description": "{component_id, days}"}}), run_scenario),
    "get_bank_price_list": (_schema("get_bank_price_list", "Illustrative price list of the simulated bank's credit line"),
                            get_bank_price_list),
}


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days
