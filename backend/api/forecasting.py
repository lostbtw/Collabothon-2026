"""Owner forecast events: stored for role 4's engine, then the forecast is recomputed.

Used by POST /forecast/events and by the chat's add_forecast_event tool. Until role 4's engine exists the
"recomputed" forecast is the latest one re-issued with the event listed (numbers unchanged); a company without
any forecast yet gets the event stored and no forecast.
"""
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from backend.api.deps import ApiError, new_id, now_iso
from backend.api.ports import _module
from backend.db.store import Store

EFFECTS = {"no_variable_flows", "no_revenue", "extra_inflow", "extra_outflow"}


def forecast_events(conn: psycopg.Connection, company: str) -> list[dict[str, Any]]:
    return [r[0] for r in conn.execute("select doc from forecast_events where company_id = %s order by seq", (company,))]


def add_forecast_event(conn: psycopg.Connection, company: str, body: dict[str, Any]) -> tuple[dict, dict | None]:
    """Store the event; return (event, new forecast or None)."""
    for field in ("label", "date_from", "date_to", "effect"):
        if not body.get(field):
            raise ApiError(422, "invalid_request", f"{field} is required")
    if body["effect"] not in EFFECTS:
        raise ApiError(422, "invalid_request", f"effect must be one of {sorted(EFFECTS)}")
    if body["date_to"] < body["date_from"]:
        raise ApiError(422, "invalid_request", "date_to is before date_from")
    event = {"id": new_id("fev"), "label": body["label"], "date_from": body["date_from"], "date_to": body["date_to"],
             "effect": body["effect"], "amount": body.get("amount"), "source": body.get("source", "owner_form")}
    conn.execute("insert into forecast_events (id, company_id, doc) values (%s, %s, %s)", (event["id"], company, Jsonb(event)))
    conn.commit()

    engine = _module("backend.finance.engine")
    if engine is not None and hasattr(engine, "recompute"):
        return event, engine.recompute(conn, company)
    s = Store(conn)
    bases = [f for f in s.list("forecast", company_id=company) if not f.get("scenario_of")]
    if not bases:
        return event, None
    latest = bases[0]
    forecast = {**latest, "id": new_id("fc"), "generated_at": now_iso(), "inputs_hash": None,
                "events": [*latest.get("events", []), event]}
    s.add("forecast", forecast, company_id=company)
    return event, forecast
