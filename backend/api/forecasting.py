"""Owner forecast events (POST /forecast/events, chat tool): store, then recompute the forecast."""
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from backend.api.deps import ApiError, new_id
from backend.api.ports import finance_engine, latest_base_forecast, reissue_forecast

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

    engine = finance_engine()
    if engine is not None and hasattr(engine, "recompute"):
        return event, engine.recompute(conn, company)
    latest = latest_base_forecast(conn, company)
    if latest is None:
        return event, None
    return event, reissue_forecast(conn, company, latest, events=[*latest.get("events", []), event])
