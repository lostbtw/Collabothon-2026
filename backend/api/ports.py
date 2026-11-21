"""Calls into role 2's executor and role 4's finance engine, with a stand-in when absent."""
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
    """Another role's module, or None while it does not exist yet."""
    try:
        if importlib.util.find_spec(name) is None:
            return None
    except ModuleNotFoundError:
        return None
    return importlib.import_module(name)


def finance_engine():
    """Role 4's engine (backend/finance/engine.py), or None until it lands."""
    return optional_module("backend.finance.engine")


def latest_base_forecast(conn: psycopg.Connection, company: str) -> dict[str, Any] | None:
    """The newest stored forecast that is not a what-if scenario."""
    bases = [f for f in Store(conn).list("forecast", company_id=company) if not f.get("scenario_of")]
    return bases[0] if bases else None


def reissue_forecast(conn: psycopg.Connection, company: str, base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """Stand-in for a recompute: the base forecast stored again under a new id with `changes` (numbers unchanged)."""
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
        return f"Sandbox Bank accepted the credit-line application: limit {_amount(p.get('limit'))}{tenor}."
    if kind == "create_payment_draft":
        when = f" for {p['pay_on']}" if p.get("pay_on") else ""
        return f"Transfer draft of {_amount(p.get('amount'))} added to the payment run{when} in the Sandbox Bank."
    if kind == "book_fx_forward":
        return (f"Forward booked in the Sandbox Bank: sell {_amount(p.get('notional'))} at {p.get('rate')} "
                f"on {p.get('value_date')}.")
    if kind == "move_to_tax_pocket":
        return f"{_amount(p.get('amount'))} moved to the tax pocket in the Sandbox Bank."
    return f"{kind.replace('_', ' ')} done in the Sandbox Bank."


def _stand_in_execute(c: psycopg.Connection, approval: dict[str, Any], action: dict[str, Any], company: str) -> dict[str, str]:
    seq = c.execute("select nextval('sim_reference_seq')").fetchone()[0]
    reference = f"SIM-{SIM_PREFIX.get(action['kind'], 'XX')}-{approval['decided_at'][:4]}-{seq:04d}"
    result = "SIMULATED: " + _describe(action)
    publish(c, new_event("execution.simulated", company,
                         {"approval_id": approval["id"], "reference": reference, "result": result}, producer="executor"))
    return {"reference": reference, "result": result}


def execute(c: psycopg.Connection, approval: dict[str, Any], action: dict[str, Any], company: str) -> dict[str, str]:
    """Run an approved action in simulation -> {"reference", "result"}."""
    executor = optional_module("backend.executor.simulated")
    if executor is not None and hasattr(executor, "execute_action"):
        return executor.execute_action(c, approval, action, company)
    return _stand_in_execute(c, approval, action, company)


def recompute_forecast(c: psycopg.Connection, company: str, note: str) -> dict[str, Any] | None:
    """New base forecast after an executed action."""
    engine = finance_engine()
    if engine is not None and hasattr(engine, "recompute"):
        return engine.recompute(c, company)
    latest = latest_base_forecast(c, company)
    if latest is None:
        return None
    return reissue_forecast(c, company, latest, assumptions=[*latest["assumptions"], note])
