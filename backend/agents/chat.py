"""The chat (5.7): questions answered from read-only tools, always with evidence.

With the model: it chooses among CHAT_TOOLS (at most 6 calls) and writes the answer; the answer is rejected if it
contains a number absent from the tool results, and the deterministic answer below is used instead.
Without the model (stand-in until #8), a small intent router calls the same tools.

Chat never moves money: CHAT_TOOLS has no execution or decision tool, and a request to move money becomes an
inbox card (request_action) that the owner decides like any other.
"""
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from backend.agents import liquidity, tools
from backend.agents.llm import run_tool_loop
from backend.agents.numbers import unexpected_numbers
from backend.agents.text import fmt_money, short_date
from backend.api import stand_ins
from backend.api.forecasting import add_forecast_event as store_forecast_event
from backend.api.recommendations import save_recommendation
from backend.db.store import Store

SUGGESTED = {
    "co_borsuk": ["Why will I be short in December?", "How much cash do I have?", "What does the credit line cost?",
                  "What do I owe my team?"],
    "co_amalfi": ["We are closed 1–30 June", "When is my cash lowest?", "How much cash do I have?"],
}
GUARDRAIL_MONEY = {"blocked": True, "reason": "Chat cannot move money; it prepared an inbox card instead"}

SYSTEM = (
    "You are Ordo's assistant for a small company's owner. Answer in plain language using only the tools. "
    "Copy numbers exactly from tool results; never compute or invent a number. You cannot move money, approve or "
    "execute anything: for such requests call request_action, which puts a card in the owner's inbox. "
    "When the owner states a future fact (closed days, a client paying on a date), call add_forecast_event. "
    'Answer with JSON {"answer": "..."}.'
)
FINAL_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string", "minLength": 1}}}

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}
MONTHS |= {"czerwca": 6, "czerwiec": 6, "lipca": 7, "juni": 6, "juli": 7, "dezember": 12, "grudnia": 12}
MONEY_WORDS = re.compile(r"\b(transfer|pay|send|wire|approve|execute|book|przelew|zapłać|überweis\w*|zahle)\b", re.I)


# --- tools ----------------------------------------------------------------------------------------------------------

def get_cash_position(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    base = conn.execute("select base_currency from companies where id = %s", (company,)).fetchone()[0]
    accounts = Store(conn).list("account", company_id=company)
    total = sum((stand_ins.convert(Decimal(a["balance"]["amount"]), a["balance"]["currency"], base)
                 for a in accounts if a.get("include_in_liquidity") and a.get("balance")), Decimal(0))
    return {"accounts": [{"id": a["id"], "name": a["name"], "balance": a.get("balance"),
                          "counted_as_company_cash": a["include_in_liquidity"]} for a in accounts],
            "total_liquidity_base": {"amount": f"{total:.2f}", "currency": base}}


def search_ledger(conn: psycopg.Connection, company: str, query: str | None = None, category: str | None = None,
                  month: str | None = None, limit: int = 20) -> dict[str, Any]:
    rows = []
    for e in Store(conn).list("ledger_entry", company_id=company):
        text = f"{e['explanation']} {e['category']} {e.get('counterparty_id') or ''}".lower()
        if (query and query.lower() not in text) or (category and e["category"] != category) or (month and not e["date"].startswith(month)):
            continue
        rows.append({k: e.get(k) for k in ("id", "date", "type", "category", "amount", "paid_by", "status", "explanation")})
    return {"rows": rows[: max(1, min(int(limit), 200))]}


def explain_recommendation(conn: psycopg.Connection, company: str, recommendation_id: str) -> dict[str, Any]:
    rec = Store(conn).get("recommendation", recommendation_id)
    if rec is None or rec["company_id"] != company:
        return {"error": f"no recommendation {recommendation_id}"}
    return {k: rec.get(k) for k in ("id", "title", "summary", "status", "control_level", "execution_mode", "evidence")} | {
        "why": rec["explanation"]["why"], "calculation": rec["explanation"].get("calculation", [])}


def add_forecast_event(conn: psycopg.Connection, company: str, label: str, date_from: str, date_to: str,
                       effect: str = "no_variable_flows", amount: dict | None = None) -> dict[str, Any]:
    """The owner's own statement (control level: owner's own action); nothing is executed."""
    event, forecast = store_forecast_event(conn, company, {"label": label, "date_from": date_from, "date_to": date_to,
                                                           "effect": effect, "amount": amount, "source": "owner_chat"})
    return {"event": event, "forecast_id": forecast["id"] if forecast else None,
            "min_balance": forecast["min_balance"] if forecast else None}


def get_fx_exposure(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    return {"items": stand_ins.FX_EXPOSURE.get(company, [])}


def request_action(conn: psycopg.Connection, company: str, description: str, kind: str = "payment") -> dict[str, Any]:
    """Anything that would move money: an inbox card instead. A credit line gets the liquidity agent's card."""
    if kind == "credit_line":
        forecast = tools.latest_forecast(conn, company)
        if forecast:
            liquidity.on_forecast_updated(conn, {"company_id": company, "occurred_at": _now(),
                                                 "payload": {"forecast_id": forecast["id"]}}, model=None)
            open_cards = [r for r in Store(conn).list("recommendation", company_id=company, type="credit_line",
                                                      status=["new", "seen"])]
            if open_cards:
                return {"recommendation_id": open_cards[0]["id"], "title": open_cards[0]["title"]}
    card = {
        "id": f"rec_chat_{uuid.uuid4().hex[:10]}", "company_id": company, "agent": "chat", "type": "info",
        "title": f"You asked: {description[:80]}",
        "summary": "Chat cannot move money. This request waits here; payments are prepared as cards by the agents "
                   "and run only after you approve them, in simulation.",
        "control_level": "recommendation", "execution_mode": "none", "status": "new", "severity": "info",
        "created_at": _now(), "valid_until": None,
        "explanation": {"why": ["Requested in the chat"], "calculation": [], "alternatives": [], "assumptions": [],
                        "confidence": 1.0, "generated_by": {"numbers": "finance-engine", "wording": "template", "trace_id": None}},
        "evidence": [{"kind": "external", "id": "chat", "label": "Your chat message", "excerpt": description[:200]}],
        "proposed_action": None, "impact": None, "subject": None, "approval_id": None,
    }
    save_recommendation(conn, card)
    return {"recommendation_id": card["id"], "title": card["title"]}


def _schema(name, description, properties=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}}}


CHAT_TOOLS: dict[str, tools.Tool] = {
    "get_cash_position": (_schema("get_cash_position", "Balances of the accounts and the company's total cash"), get_cash_position),
    "get_forecast": (_schema("get_forecast", "The latest cash forecast: lowest balance, alerts, components, stress case"),
                     lambda conn, company: tools.get_forecast(conn, company)),
    "search_ledger": (_schema("search_ledger", "Rows of the approved ledger", {
        "query": {"type": "string"}, "category": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM"},
        "limit": {"type": "integer"}}), search_ledger),
    "explain_recommendation": (_schema("explain_recommendation", "Why an inbox card proposes what it does",
                                       {"recommendation_id": {"type": "string"}}, ["recommendation_id"]), explain_recommendation),
    "add_forecast_event": (_schema("add_forecast_event", "Record a future fact the owner states, e.g. closed 1-30 June", {
        "label": {"type": "string"}, "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "effect": {"type": "string", "enum": ["no_variable_flows", "no_revenue", "extra_inflow", "extra_outflow"]},
        "amount": {"type": "object"}}, ["label", "date_from", "date_to", "effect"]), add_forecast_event),
    "get_fx_exposure": (_schema("get_fx_exposure", "Open foreign-currency invoices and their exchange-rate risk"), get_fx_exposure),
    "request_action": (_schema("request_action", "Put a request that would move money into the owner's inbox", {
        "description": {"type": "string"}, "kind": {"type": "string", "enum": ["payment", "transfer", "credit_line", "fx_hedge"]}},
        ["description"]), request_action),
}


# --- answers ----------------------------------------------------------------------------------------------------------

def _now() -> str:
    from backend.api.deps import now_iso

    return now_iso()


def _as_of(conn: psycopg.Connection, company: str) -> date:
    return conn.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0]


def _closed_period(message: str, as_of: date) -> tuple[str, str] | None:
    m = re.search(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\.?\s+([A-Za-zÀ-ž]+)", message)
    if not m or m.group(3).lower() not in MONTHS:
        return None
    month = MONTHS[m.group(3).lower()]
    year = as_of.year if date(as_of.year, month, int(m.group(2))) >= as_of else as_of.year + 1
    return date(year, month, int(m.group(1))).isoformat(), date(year, month, int(m.group(2))).isoformat()


def _evidence(results: list[Any]) -> list[dict[str, Any]]:
    """Evidence links for whatever the tools returned."""
    links: list[dict[str, Any]] = []

    def add(link):
        if link and link not in links:
            links.append(link)

    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("forecast_id"):
            add({"kind": "forecast", "id": r["forecast_id"], "label": "Cash forecast", "url": f"/forecast/{r['forecast_id']}"})
        for e in r.get("evidence", []) or []:
            add(e)
        for row in r.get("rows", []) or []:
            add({"kind": "ledger_entry", "id": row["id"], "label": row["explanation"][:80], "url": f"/ledger/{row['id']}"})
        if r.get("recommendation_id"):
            add({"kind": "recommendation", "id": r["recommendation_id"], "label": r.get("title", "Inbox card"),
                 "url": f"/recommendations/{r['recommendation_id']}"})
        for a in r.get("accounts", []) or []:
            add({"kind": "external", "id": a["id"], "label": f"Account {a['name']}", "url": f"/accounts/{a['id']}"})
    return links


def _component_evidence(conn: psycopg.Connection, forecast_id: str) -> list[dict[str, Any]]:
    forecast = Store(conn).get("forecast", forecast_id) or {"components": []}
    return [e for c in forecast["components"] for e in c.get("evidence", [])]


def deterministic(conn: psycopg.Connection, company: str, message: str) -> tuple[str, list, list, str | None, dict | None]:
    """(answer, evidence, tool trace, created card id, guardrail) without a model."""
    text = message.lower()
    period = _closed_period(message, _as_of(conn, company))
    if period and re.search(r"closed|close|zamkni|geschlossen|holiday|urlaub|wakacje", text):
        args = {"label": message.strip()[:80], "date_from": period[0], "date_to": period[1], "effect": "no_variable_flows"}
        result = add_forecast_event(conn, company, **args)
        answer = f"Noted: closed {short_date(period[0])} to {short_date(period[1])} {period[0][:4]}. It is in the forecast as your event."
        if result["min_balance"]:
            low = result["min_balance"]
            answer += f" The lowest balance is now {liquidity._signed(low['amount'])} on {short_date(low['date'])}."
        return answer, _evidence([result]), [{"tool": "add_forecast_event", "arguments": args, "duration_ms": 0}], None, None

    if MONEY_WORDS.search(message) or "credit line" in text:
        kind = "credit_line" if "credit line" in text else "payment"
        result = request_action(conn, company, message, kind)
        answer = (f"I cannot move money from the chat. I put this in your inbox: \"{result['title']}\". "
                  "It runs only after you approve it, in simulation.")
        return (answer, _evidence([result]), [{"tool": "request_action", "arguments": {"description": message, "kind": kind},
                                               "duration_ms": 0}], result["recommendation_id"], GUARDRAIL_MONEY)

    if re.search(r"short|gap|minus|lowest|low point|negative|zabrak|fehlt", text):
        facts = None
        forecast = tools.latest_forecast(conn, company)
        if forecast:
            facts = liquidity.facts_for(conn, company, forecast["id"])
        if not forecast:
            return "There is no forecast yet.", [], [], None, None
        low = forecast["min_balance"]
        if facts is None:
            answer = (f"No gap is forecast: the lowest balance is {liquidity._signed(low['amount'])} "
                      f"on {short_date(low['date'])}.")
        else:
            alert = facts["alert"]
            reasons = "; ".join(liquidity._reasons(facts))
            answer = (f"The accounts go below zero from {short_date(alert['date_from'])} and reach "
                      f"{liquidity._signed(low['amount'])} on {short_date(low['date'])}. Main reasons: {reasons}.")
        g = tools.get_forecast(conn, company)
        evidence = _evidence([g]) + [e for e in _component_evidence(conn, forecast["id"]) if e]
        open_cards = Store(conn).list("recommendation", company_id=company, type="credit_line", status=["new", "seen"])
        if open_cards:
            answer += f" Proposed fix in your inbox: {open_cards[0]['title']}."
            evidence.append({"kind": "recommendation", "id": open_cards[0]["id"], "label": open_cards[0]["title"],
                             "url": f"/recommendations/{open_cards[0]['id']}"})
        return answer, evidence, [{"tool": "get_forecast", "arguments": {}, "duration_ms": 0}], None, None

    if re.search(r"cash|balance|how much|money|ile|wie viel|saldo", text):
        result = get_cash_position(conn, company)
        answer = f"You have {fmt_money(result['total_liquidity_base'])} of company cash today."
        return answer, _evidence([result]), [{"tool": "get_cash_position", "arguments": {}, "duration_ms": 0}], None, None

    return ("I can explain your cash forecast, your inbox cards and your ledger, and note future events such as "
            "closed days. Try one of the suggested questions."), [], [], None, None


def answer(conn: psycopg.Connection, company: str, message: str, session_id: str | None, model: Any) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    created = guardrail = None
    text = evidence = None
    if model is not None:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": message}]
        result, results = run_tool_loop(model, conn, company, messages, CHAT_TOOLS, FINAL_SCHEMA, trace=trace)
        for r in results:
            if isinstance(r, dict) and r.get("recommendation_id") and any(t["tool"] == "request_action" for t in trace):
                created, guardrail = r["recommendation_id"], GUARDRAIL_MONEY
        if result and not unexpected_numbers([result["answer"]], [results, message]):
            text, evidence = result["answer"], _evidence(results)
            for r in results:
                if isinstance(r, dict) and r.get("forecast_id"):
                    evidence += [e for e in _component_evidence(conn, r["forecast_id"]) if e not in evidence]
    if text is None:
        text, evidence, fallback_trace, fallback_created, fallback_guardrail = deterministic(conn, company, message)
        trace = trace or fallback_trace
        created = created or fallback_created
        guardrail = guardrail or fallback_guardrail
    return {
        "session_id": session_id or f"chat_{uuid.uuid4().hex[:10]}",
        "answer": text,
        "evidence": evidence or [],
        "table": None,
        "tool_calls": trace,
        "created_recommendation_id": created,
        "guardrail": guardrail,
        "trace_id": None,
        "suggested_questions": SUGGESTED.get(company, SUGGESTED["co_borsuk"]),
    }
