"""What-if scenarios, the stress case and credit-line sizing, computed from a forecast's own points and components."""
import copy
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from .forecast import summarise
from .settings import LATE_CONFIDENCE, SIZING_STEP, STRESS_EXTRA_DAYS

LINES = ("balance", "low", "high")


def _money(value: Decimal, currency: str) -> dict[str, str]:
    return {"amount": f"{value:.2f}", "currency": currency}


def _add(points: list[dict], start: str, end: str | None, delta: Decimal) -> None:
    for p in points:
        if p["date"] >= start and (end is None or p["date"] < end):
            for k in LINES:
                if p.get(k) is not None:
                    p[k] = f"{Decimal(p[k]) + delta:.2f}"


def _move(points: list[dict], amount: Decimal, old: str, new: str) -> None:
    if new > old:
        _add(points, old, new, -amount)
    elif new < old:
        _add(points, new, old, amount)


def _component(f: dict, component_id: str | None = None, document_id: str | None = None) -> dict:
    for c in f["components"]:
        if component_id and c["id"] == component_id:
            return c
        if document_id and (c["id"] == f"c_{document_id}" or c["kind"] not in ("tax", "social_security") and any(
                e.get("kind") == "document" and e.get("id") == document_id for e in c.get("evidence", []))):
            return c
    raise KeyError(component_id or document_id)


def _finish(f: dict) -> dict:
    as_of = date.fromisoformat(f["as_of_date"])
    buffer = Decimal(f["safety_buffer"]["amount"]) if f.get("safety_buffer") else None
    f["min_balance"], f["first_negative_date"], f["alerts"] = summarise(f["points"], as_of, f["base_currency"], buffer)
    return f


def with_changes(base: dict, body: dict[str, Any]) -> dict:
    f = copy.deepcopy(base)
    currency = f["base_currency"]
    evidence = [{"kind": "forecast", "id": base["id"], "label": "Base forecast", "url": f"/forecast/{base['id']}"}]

    if body.get("credit_line"):
        limit = Decimal(body["credit_line"]["limit"]["amount"])
        start = body["credit_line"].get("from") or f["as_of_date"]
        _add(f["points"], start, None, limit)
        f["components"].append({"id": "c_credit_line", "label": f"Credit line {limit:,.2f} {currency} (simulated)",
                                "kind": "scenario_action", "amount_base": _money(limit, currency),
                                "schedule": f"available from {start}", "dates": [start], "confidence": 1.0,
                                "evidence": evidence})

    if body.get("shift_receivable"):
        shift = body["shift_receivable"]
        c = _component(f, document_id=shift["document_id"])
        old, new = c["dates"][0], shift["new_date"]
        _move(f["points"], Decimal(c["amount_base"]["amount"]), old, new)
        c.update(dates=[new], schedule=f"moved from {old} to {new} (scenario)")
        f["assumptions"].append(f"Scenario: {c['label']} paid on {new} instead of {old}")

    if body.get("shift_payable"):
        shift = body["shift_payable"]
        c = _component(f, component_id=shift["component_id"])
        each = Decimal(c["amount_base"]["amount"]) / len(c["dates"])
        moved = []
        for old in c["dates"]:
            new = (date.fromisoformat(old) + timedelta(days=int(shift["days"]))).isoformat()
            _move(f["points"], each, old, new)
            moved.append(new)
        c.update(dates=moved, schedule=f"{c.get('schedule') or ''}; moved {shift['days']} days (scenario)".strip("; "))
        f["assumptions"].append(f"Scenario: {c['label']} paid {shift['days']} days later")

    return _finish(f)


def late_receivable(f: dict) -> dict | None:
    late = [c for c in f["components"]
            if c["kind"] == "known_receivable" and c["dates"] and c["confidence"] < LATE_CONFIDENCE]
    return max(late, key=lambda c: Decimal(c["amount_base"]["amount"]), default=None)


def client_of(component: dict) -> str:
    words = component["label"].split()
    if words and words[0].lower() == "invoice" and len(words) > 2:
        words = words[2:]
    return (words[0] if words else component["id"]).rstrip(",")


def stress_of(f: dict) -> dict[str, Any]:
    currency = f["base_currency"]
    receivable = late_receivable(f)
    if receivable is None:
        low = f["min_balance"]
        return {"label": "No late-paying client in the forecast", "date": low["date"], "balance": low["amount"],
                "receivable_component_id": None, "extra_days": 0}
    amount = Decimal(receivable["amount_base"]["amount"])
    old = receivable["dates"][0]
    new = (date.fromisoformat(old) + timedelta(days=STRESS_EXTRA_DAYS)).isoformat()
    points = copy.deepcopy(f["points"])
    _move(points, amount, old, new)
    # the money of the arrival day lands last: payments due that day hit first
    candidates = [(Decimal(p["balance"]), p["date"]) for p in points if p["date"] < new]
    candidates += [(Decimal(p["balance"]) - amount, p["date"]) for p in points if p["date"] == new]
    low, day = min(candidates, key=lambda x: (x[0], x[1]))
    return {"label": f"{client_of(receivable)} pays {date.fromisoformat(new).day} {date.fromisoformat(new):%b}",
            "date": day, "balance": _money(low, currency), "receivable_component_id": receivable["id"],
            "extra_days": STRESS_EXTRA_DAYS}


def credit_line_size(f: dict, stress: dict | None = None) -> dict[str, Any]:
    currency = f["base_currency"]
    stress = stress or stress_of(f)
    worst = min(Decimal(f["min_balance"]["amount"]["amount"]), Decimal(stress["balance"]["amount"]))
    shortfall = max(-worst, Decimal(0))
    limit = (shortfall / SIZING_STEP).to_integral_value(rounding=ROUND_CEILING) * SIZING_STEP
    basis = "stress case" if Decimal(stress["balance"]["amount"]) < Decimal(f["min_balance"]["amount"]["amount"]) \
        else "forecast"
    return {"limit": _money(limit, currency), "shortfall": _money(shortfall, currency), "basis": basis,
            "rule": f"worst shortfall ({basis}) rounded up to {SIZING_STEP:,.0f} {currency}",
            "stress": stress}
