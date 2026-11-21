"""Calls into the simulated executor and the finance engine, with a stand-in when absent."""
import importlib
import importlib.util
from decimal import Decimal
from typing import Any

import psycopg

from backend.api.deps import new_id, now_iso
from backend.db.events import new_event, publish
from backend.db.store import Store

SIM_PREFIX = {
    "apply_credit_line": "CL",
    "create_payment_draft": "PD",
    "book_fx_forward": "FX",
    "move_to_tax_pocket": "TX",
    "schedule_transfer": "TR",
    "send_email_draft": "EM",
    "book_ledger_entries": "LE",
}


def optional_module(name: str):
    try:
        if importlib.util.find_spec(name) is None:
            return None
    except ModuleNotFoundError:
        return None
    return importlib.import_module(name)


def finance_engine():
    return optional_module("backend.finance.engine")


def latest_base_forecast(conn: psycopg.Connection, company: str) -> dict[str, Any] | None:
    bases = [f for f in Store(conn).list("forecast", company_id=company) if not f.get("scenario_of")]
    return bases[0] if bases else None


def reissue_forecast(conn: psycopg.Connection, company: str, base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    forecast = {**base, "id": new_id("fc"), "generated_at": now_iso(), "inputs_hash": None, **changes}
    Store(conn).add("forecast", forecast, company_id=company)
    return forecast


def _amount(m: dict[str, str] | None) -> str:
    if not m:
        return ""
    value = Decimal(m["amount"])
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{text} {m['currency']}"


def _describe(action: dict[str, Any]) -> str:
    p = action.get("params", {})
    kind = action["kind"]
    if kind == "apply_credit_line":
        tenor = f", {p['tenor_days']} days" if p.get("tenor_days") else ""
        return f"Commerzbank accepted the credit-line application: limit {_amount(p.get('limit'))}{tenor}."
    if kind == "create_payment_draft":
        when = f" for {p['pay_on']}" if p.get("pay_on") else ""
        return f"Transfer draft of {_amount(p.get('amount'))} added to the payment run{when} at Commerzbank."
    if kind == "book_fx_forward":
        return (f"Forward booked at Commerzbank: sell {_amount(p.get('notional'))} at {p.get('rate')} "
                f"on {p.get('value_date')}.")
    if kind == "move_to_tax_pocket":
        return f"{_amount(p.get('amount'))} moved to your tax account at Commerzbank."
    return f"{kind.replace('_', ' ')} done at Commerzbank."


def _stand_in_execute(c: psycopg.Connection, approval: dict[str, Any], action: dict[str, Any], company: str) -> dict[str, str]:
    seq = c.execute("select nextval('sim_reference_seq')").fetchone()[0]
    reference = f"SIM-{SIM_PREFIX.get(action['kind'], 'XX')}-{approval['decided_at'][:4]}-{seq:04d}"
    result = "SIMULATED: " + _describe(action)
    publish(c, new_event("execution.simulated", company,
                         {"approval_id": approval["id"], "reference": reference, "result": result}, producer="executor"))
    return {"reference": reference, "result": result}


def execute(c: psycopg.Connection, approval: dict[str, Any], action: dict[str, Any], company: str) -> dict[str, str]:
    executor = optional_module("backend.executor.simulated")
    if executor is not None and hasattr(executor, "execute_action"):
        return executor.execute_action(c, approval, action, company)
    return _stand_in_execute(c, approval, action, company)


def recompute_forecast(c: psycopg.Connection, company: str, note: str) -> dict[str, Any] | None:
    engine = finance_engine()
    if engine is not None and hasattr(engine, "recompute"):
        return engine.recompute(c, company)
    latest = latest_base_forecast(c, company)
    if latest is None:
        return None
    return reissue_forecast(c, company, latest, assumptions=[*latest["assumptions"], note])
