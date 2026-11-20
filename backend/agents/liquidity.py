"""The liquidity agent (5.6). On forecast.updated with a new or changed cash-gap alert it proposes one credit-line
card: reasons, calculation, cheaper alternatives first, the stress case and evidence.

Numbers come only from the tools (role 4's engine, stand-ins until #44). The card is first built from a template;
the model may then rewrite the wording (title, summary, reasons) after choosing its own tool calls. Its text is
rejected if it contains any number absent from the tool results, and any failure keeps the template.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg

from backend import settings
from backend.agents import stand_ins, tools
from backend.agents.llm import default_client, run_tool_loop
from backend.agents.numbers import unexpected_numbers
from backend.agents.text import fmt_money, short_date
from backend.api.recommendations import save_recommendation
from backend.db.events import new_event, publish
from backend.db.store import Store

_DEFAULT = object()

FINAL_SCHEMA = {
    "type": "object",
    "required": ["title", "summary", "why"],
    "properties": {
        "title": {"type": "string", "minLength": 5, "maxLength": 90},
        "summary": {"type": "string", "minLength": 10, "maxLength": 600},
        "why": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
    },
}

SYSTEM = (
    "You are the liquidity agent of Ordo, an autonomous CFO for a small company. A cash gap is coming. "
    "Call the tools you need, then answer with JSON {title, summary, why} for a card that proposes the credit line "
    "in the facts. The title is an instruction to the owner. Write plain language for a busy owner. "
    "Copy every number exactly from the tool results or the facts; never compute, round or invent a number. "
    'Answer with JSON only, exactly this shape: {"title": "...", "summary": "...", "why": ["reason 1", "reason 2", "reason 3"]}.'
)


def _money(amount: Decimal, currency: str) -> dict[str, str]:
    return {"amount": f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}", "currency": currency}


def signed_amount(m: dict[str, str]) -> str:
    sign = "-" if Decimal(m["amount"]) < 0 else ""
    return sign + fmt_money(m, cents=False)


def earliest_gap(forecast: dict[str, Any]) -> dict[str, Any] | None:
    gaps = [a for a in forecast["alerts"] if a["type"] in ("cash_gap", "below_buffer")]
    return sorted(gaps, key=lambda a: a["date_from"])[0] if gaps else None


def facts_for(conn: psycopg.Connection, company: str, forecast_id: str) -> dict[str, Any] | None:
    """Every number the card shows, from the engine tools. None when there is no gap to act on."""
    f = tools.get_forecast(conn, company, forecast_id)
    if "error" in f:
        return None
    alert = earliest_gap(f)
    if alert is None:
        return None
    currency = f["base_currency"]
    shortfall = Decimal(alert["max_shortfall"]["amount"])
    stress = f.get("stress_case")
    stress_shortfall = max(shortfall, -Decimal(stress["balance"]["amount"])) if stress else shortfall
    prices = tools.get_bank_price_list(conn, company)
    min_limit = Decimal(prices["min_limit"]["amount"]) if prices.get("min_limit") else None
    limit = stand_ins.size_credit_line(stress_shortfall, min_limit)
    gap_days = max(tools.days_between(alert["date_from"], alert["date_to"]), 1)
    rate = Decimal(prices.get("interest_rate_pct", "0")) / 100
    interest = (shortfall * gap_days * rate / 365).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    fee = (limit * Decimal(prices.get("arrangement_fee_pct_of_limit", "0")) / 100).quantize(Decimal("1"))
    deadline = date.fromisoformat(alert["date_from"])
    scenario = tools.run_scenario(conn, company, credit_line_limit=f"{limit:.2f}",
                                  from_date=(deadline - timedelta(days=3)).isoformat())
    return {
        "forecast": f,
        "alert": alert,
        "currency": currency,
        "shortfall": _money(shortfall, currency),
        "low": f["min_balance"],
        "stress": stress,
        "stress_shortfall": _money(stress_shortfall, currency),
        "limit": _money(limit, currency),
        "gap_days": gap_days,
        "interest": _money(interest, currency),
        "fee": _money(fee, currency),
        "prices": prices,
        "deadline": deadline.isoformat(),
        "scenario": scenario,
        "overdue": tools.list_overdue_receivables(conn, company)["items"],
    }


def reasons(facts: dict[str, Any]) -> list[str]:
    alert = facts["alert"]
    comps = facts["forecast"]["components"]
    outflows = sorted((c for c in comps if Decimal(c["amount_base"]["amount"]) < 0 and c.get("dates")
                       and c["dates"][0] <= alert["date_to"]), key=lambda c: Decimal(c["amount_base"]["amount"]))
    late = [o for o in facts["overdue"] if o.get("expected_date") and o["expected_date"] >= alert["date_from"]]
    why = []
    if outflows:
        c = outflows[0]
        why.append(f"{c['label']}: {fmt_money(c['amount_base'], cents=False)} leave on {short_date(c['dates'][0])}")
    for o in late[:1]:
        why.append(f"{o['label']}; expected {short_date(o['expected_date'])}" + (f" ({o['schedule']})" if o.get("schedule") else ""))
    for c in outflows[1:]:
        if len(why) >= 3:
            break
        why.append(f"{c['label']}: {fmt_money(c['amount_base'], cents=False)} on {short_date(c['dates'][0])}")
    return why[:3]


def template_recommendation(company: str, facts: dict[str, Any], at: str) -> dict[str, Any]:
    alert, low, limit, currency = facts["alert"], facts["low"], facts["limit"], facts["currency"]
    deadline = date.fromisoformat(facts["deadline"])
    stress = facts["stress"]
    client = next((o["client"] for o in facts["overdue"] if o.get("client")), None)

    calculation = [{"label": "Lowest projected balance", "value": f"{signed_amount(low['amount'])} on {short_date(low['date'])}",
                    "formula": None}]
    if stress:
        calculation.append({"label": f"Stress case ({stress['label']})",
                            "value": f"{signed_amount(stress['balance'])} on {short_date(stress['date'])}", "formula": None})
    calculation += [
        {"label": "Proposed limit", "value": fmt_money(limit, cents=False),
         "formula": f"{'stress' if stress else 'largest'} shortfall {fmt_money(facts['stress_shortfall'], cents=False)} "
                    f"rounded up to the next 5,000"},
        {"label": "Estimated cost",
         "value": f"about {fmt_money(facts['interest'], cents=False)} interest + {fmt_money(facts['fee'], cents=False)} fee",
         "formula": f"{fmt_money(facts['shortfall'], cents=False)} x {facts['gap_days']} days x "
                    f"{facts['prices'].get('interest_rate_pct')}% / 365, fee {facts['prices'].get('arrangement_fee_pct_of_limit')}% "
                    f"of limit (illustrative price list of the simulated bank)"},
    ]
    zero = {"amount": "0.00", "currency": currency}
    alternatives = []
    if client:
        alternatives.append({"label": f"Send {client} a payment reminder today", "pros": "Free; may remove the gap entirely",
                             "cons": "Outcome uncertain", "cost": zero})
    alternatives += [
        {"label": "Pay contractors 7 days later", "pros": "No bank cost", "cons": "Breaks agreed payment dates", "cost": zero},
        {"label": "Do nothing", "pros": None, "cons": "Unarranged overdraft or failed salary transfers", "cost": None},
    ]
    summary = (f"From {short_date(alert['date_from'])} to {short_date(alert['date_to'])} the accounts will be "
               f"{fmt_money(facts['shortfall'], cents=False)} short")
    if stress:
        summary += f", or {fmt_money(facts['stress_shortfall'], cents=False)} short if {stress['label']}"
    summary += f". A {fmt_money(limit, cents=False)} revolving line covers {'both cases' if stress else 'the gap'}."
    scenario_low = facts["scenario"].get("min_balance", {}).get("amount")
    total_cost = _money(Decimal(facts["interest"]["amount"]) + Decimal(facts["fee"]["amount"]), currency)
    forecast_id = facts["forecast"]["forecast_id"]
    return {
        "id": f"rec_cl_{forecast_id}",
        "company_id": company,
        "agent": "liquidity",
        "type": "credit_line",
        "title": f"Open a {fmt_money(limit, cents=False)} credit line before {deadline.day} {deadline.strftime('%B')}",
        "summary": summary,
        "control_level": "approval_required",
        "execution_mode": "simulated",
        "status": "new",
        "severity": alert.get("severity", "critical"),
        "created_at": at,
        "valid_until": f"{(deadline - timedelta(days=3)).isoformat()}T23:59:59Z",
        "explanation": {
            "why": reasons(facts),
            "calculation": calculation,
            "alternatives": alternatives,
            "assumptions": ["Interest rate and fee come from the simulated bank's price list, not a real offer"],
            "confidence": min((c["confidence"] for c in facts["forecast"]["components"] if c["kind"] != "opening_balance"),
                              default=0.8),
            "generated_by": {"numbers": "finance-engine", "wording": "template", "trace_id": None},
        },
        "evidence": [
            {"kind": "forecast", "id": forecast_id, "label": f"{facts['forecast'].get('as_of_date')} cash forecast",
             "url": f"/forecast/{forecast_id}"},
            *[{"kind": "document", "id": o["document_id"], "label": o["label"], "url": f"/documents/{o['document_id']}"}
              for o in facts["overdue"] if o.get("document_id")],
        ],
        "proposed_action": {
            "kind": "apply_credit_line",
            "params": {"limit": limit, "tenor_days": 60, "bank": facts["prices"].get("bank", "Sandbox Bank"),
                       "product": facts["prices"].get("product"),
                       "alert": {"date_from": alert["date_from"], "max_shortfall": alert["max_shortfall"]}},
            "preview": f"SIMULATED: sends a credit-line application for {fmt_money(limit, cents=False)} / 60 days to the "
                       f"Sandbox Bank. No real bank is contacted.",
        },
        "impact": {
            "cash_effect": limit,
            "cost": total_cost,
            "min_balance_before": low["amount"],
            "min_balance_after": scenario_low,
            "scenario_forecast_id": facts["scenario"].get("forecast_id"),
        },
        "subject": {"kind": "forecast", "id": forecast_id, "label": "Cash gap alert"},
        "approval_id": None,
    }


def _model_wording(model: Any, conn: psycopg.Connection, company: str, facts: dict[str, Any], card: dict[str, Any]) -> dict | None:
    engine_facts = {"limit": card["proposed_action"]["params"]["limit"], "deadline": facts["deadline"],
                    "calculation": card["explanation"]["calculation"],
                    "alternatives": [a["label"] for a in card["explanation"]["alternatives"]]}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Facts from the finance engine: {engine_facts}. Template title: {card['title']}"}]
    answer, results = run_tool_loop(model, conn, company, messages, tools.LIQUIDITY_TOOLS, FINAL_SCHEMA)
    if answer is None:
        return None
    texts = [answer["title"], answer["summary"], *answer["why"]]
    invented = unexpected_numbers(texts, [results, engine_facts, card["title"]])
    if invented:
        return None
    return answer


def _open_credit_lines(s: Store, company: str) -> list[dict[str, Any]]:
    return [r for r in s.list("recommendation", company_id=company, agent="liquidity", status=["new", "seen"])
            if r["type"] == "credit_line"]


def on_forecast_updated(conn: psycopg.Connection, event: dict[str, Any], model: Any = _DEFAULT) -> str | None:
    """Handler for `forecast.updated`. Returns the id of the card created, or None."""
    company = event["company_id"]
    facts = facts_for(conn, company, event["payload"].get("forecast_id"))
    if facts is None:
        return None
    s = Store(conn)
    signature = {"date_from": facts["alert"]["date_from"], "max_shortfall": facts["alert"]["max_shortfall"]}
    open_credit_lines = _open_credit_lines(s, company)
    if any(r["proposed_action"]["params"].get("alert") == signature for r in open_credit_lines):
        return None  # same alert, card already in the inbox

    card = template_recommendation(company, facts, event["occurred_at"])
    for old in open_credit_lines:
        s.put("recommendation", {**old, "status": "superseded"})
        publish(conn, new_event("recommendation.status_changed", company,
                                {"recommendation_id": old["id"], "status": "superseded"}, producer="agents"))
    if not save_recommendation(conn, card):
        return None
    # The template card is in the inbox now; the model's wording replaces its text only if it passes the checks
    # and the owner has not decided the card meanwhile.
    if model is _DEFAULT:
        model = default_client()
    if model is not None:
        wording = _model_wording(model, conn, company, facts, card)
        current = s.get("recommendation", card["id"])
        if wording and current and current["status"] in ("new", "seen"):
            current["title"], current["summary"] = wording["title"], wording["summary"]
            current["explanation"]["why"] = wording["why"]
            current["explanation"]["generated_by"]["wording"] = settings.llm_model()
            s.put("recommendation", current)
            publish(conn, new_event("recommendation.status_changed", company,
                                    {"recommendation_id": card["id"], "status": current["status"]}, producer="agents"))
    return card["id"]
