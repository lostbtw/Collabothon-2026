"""The chat: read-only tools, number-checked answers. It never moves money: such requests become inbox cards."""
import calendar
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from backend import tracing
from backend.agents import guardrails, liquidity, tools
from backend.agents.llm import run_tool_loop
from backend.agents.numbers import unexpected_numbers
from backend.agents.sql import VIEWS, run_readonly_sql
from backend.agents.text import fmt_money, short_date
from backend.api import owner, stand_ins
from backend.api.forecasting import add_forecast_event as store_forecast_event
from backend.api.ports import finance_engine
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
    "Refuse politely anything that is not about this company's finances. If a tool returns an error, fix the "
    "arguments or choose another tool. "
    'Answer with JSON {"answer": "..."}.'
)
FINAL_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string", "minLength": 1}}}

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}
MONTHS |= {"czerwca": 6, "czerwiec": 6, "lipca": 7, "juni": 6, "juli": 7, "dezember": 12, "grudnia": 12}
MONEY_WORDS = re.compile(r"\b(transfer|pay|send|wire|approve|execute|book|przelew|zapłać|überweis\w*|zahle)\b", re.I)


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
    event, forecast = store_forecast_event(conn, company, {"label": label, "date_from": date_from, "date_to": date_to,
                                                           "effect": effect, "amount": amount, "source": "owner_chat"})
    return {"event": event, "forecast_id": forecast["id"] if forecast else None,
            "min_balance": forecast["min_balance"] if forecast else None}


def get_fx_exposure(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    engine = finance_engine()
    if engine is not None and hasattr(engine, "fx_exposure"):
        return engine.fx_exposure(conn, company)
    return {"items": stand_ins.FX_EXPOSURE.get(company, [])}


def request_action(conn: psycopg.Connection, company: str, description: str, kind: str = "payment") -> dict[str, Any]:
    """Anything that would move money: an inbox card instead. A credit line gets the liquidity agent's card."""
    if kind == "credit_line":
        forecast = tools.latest_forecast(conn, company)
        if forecast:
            liquidity.on_forecast_updated(conn, {"company_id": company, "occurred_at": _now(),
                                                 "payload": {"forecast_id": forecast["id"]}}, model=None)
            open_credit_lines = [r for r in Store(conn).list("recommendation", company_id=company, type="credit_line",
                                                      status=["new", "seen"])]
            if open_credit_lines:
                return {"recommendation_id": open_credit_lines[0]["id"], "title": open_credit_lines[0]["title"]}
    card = {
        "id": f"rec_chat_{uuid.uuid4().hex[:10]}", "company_id": company, "agent": "chat", "type": "info",
        "title": f"You asked: {description[:80]}",
        "summary": "Chat cannot move money. This request waits here; payments are prepared as cards by the agents "
                   "and run only after you approve them, in simulation.",
        "control_level": "recommendation", "execution_mode": "none", "status": "new", "severity": "info",
        "created_at": _now(), "valid_until": None,
        "explanation": {"why": ["Requested in the chat"], "calculation": [], "alternatives": [], "assumptions": [],
                        "confidence": 1.0, "generated_by": {"numbers": "finance-engine", "wording": "template",
                                                          "trace_id": tracing.trace_id()}},
        "evidence": [{"kind": "external", "id": "chat", "label": "Your chat message", "excerpt": description[:200]}],
        "proposed_action": None, "impact": None, "subject": None, "approval_id": None,
    }
    save_recommendation(conn, card)
    return {"recommendation_id": card["id"], "title": card["title"]}


def _month_before(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def get_clients(conn: psycopg.Connection, company: str, month: str | None = None) -> dict[str, Any]:
    month = month or _as_of(conn, company).isoformat()[:7]
    data = owner.clients(conn, company, month, persist_delays=False)
    clients = [{"name": c["name"], "paid_in_month": c["paid_in_month"], "still_owes": c["open_total_base"],
                "late_invoices": [{"number": i["number"], "amount": i["gross"], "days_late": i["days_late"]}
                                  for i in c["open_invoices"] if i["days_late"] > 0],
                "usually_pays_days_late": c["typical_payment_delay_days"]} for c in data["items"]]
    return {"month": month, "clients": clients, "totals": data["totals"],
            "evidence": [{"kind": "external", "id": "clients", "label": "Clients and what they owe", "url": "/money/clients"}]}


def get_month_costs(conn: psycopg.Connection, company: str, month: str | None = None) -> dict[str, Any]:
    month = month or _as_of(conn, company).isoformat()[:7]
    before = _month_before(month)

    def sums(m: str) -> dict[str, Decimal]:
        start, end = owner.month_range(m)
        return {r["key"]: -Decimal(r["amount_base"]["amount"]) for r in owner.bank_summary(conn, company, start, end)
                if Decimal(r["amount_base"]["amount"]) < 0 and r["key"] not in owner.NOT_COSTS}

    now, then = sums(month), sums(before)
    base = owner.settings(conn, company)["company"]["base_currency"]
    rows = [{"category": k, "amount": owner.money(now.get(k, Decimal(0)), base), "month_before": owner.money(then.get(k, Decimal(0)), base),
             "change": owner.money(now.get(k, Decimal(0)) - then.get(k, Decimal(0)), base)} for k in sorted(set(now) | set(then))]
    rows.sort(key=lambda r: -abs(Decimal(r["change"]["amount"])))
    total_now, total_then = sum(now.values(), Decimal(0)), sum(then.values(), Decimal(0))
    return {"month": month, "month_before": before, "costs": owner.money(total_now, base), "costs_month_before": owner.money(total_then, base),
            "change": owner.money(total_now - total_then, base), "by_category": rows,
            "evidence": [{"kind": "external", "id": f"costs_{month}", "label": f"Costs of {month} by type", "url": f"/money?month={month}"}]}


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
    "get_clients": (_schema("get_clients", "Clients: what each paid in a month, what they still owe, which invoices are late",
                            {"month": {"type": "string", "description": "YYYY-MM, default this month"}}), get_clients),
    "get_month_costs": (_schema("get_month_costs", "Costs of a month by category compared with the month before (why costs went up or down)",
                                {"month": {"type": "string", "description": "YYYY-MM, default this month"}}), get_month_costs),
    "request_action": (_schema("request_action", "Put a request that would move money into the owner's inbox", {
        "description": {"type": "string"}, "kind": {"type": "string", "enum": ["payment", "transfer", "credit_line", "fx_hedge"]}},
        ["description"]), request_action),
    "run_readonly_sql": (_schema("run_readonly_sql", "One read-only SELECT over the views " + ", ".join(VIEWS)
                                 + " (at most 200 rows, 3 s)", {"sql": {"type": "string"}}, ["sql"]), run_readonly_sql),
}

HISTORY_TURNS = 6


def history(conn: psycopg.Connection, session_id: str, company: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """select role, content from (select role, content, seq from chat_messages
           where session_id = %s and company_id = %s order by seq desc limit %s) t order by seq""",
        (session_id, company, HISTORY_TURNS * 2)).fetchall()
    return [{"role": r, "content": c} for r, c in rows]


def remember(conn: psycopg.Connection, session_id: str, company: str, question: str, reply: str) -> None:
    conn.execute("insert into chat_messages (session_id, company_id, role, content) values (%s, %s, 'user', %s), "
                 "(%s, %s, 'assistant', %s)", (session_id, company, question, session_id, company, reply))
    conn.commit()


def _now() -> str:
    from backend.api.deps import now_iso

    return now_iso()


def _as_of(conn: psycopg.Connection, company: str) -> date:
    return conn.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0]


def _closed_period(message: str, as_of: date) -> tuple[str, str] | None:
    m = re.search(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\.?\s+([A-Za-zÀ-ž]+)", message)
    if m and m.group(3).lower() in MONTHS:
        month, first, last = MONTHS[m.group(3).lower()], int(m.group(1)), int(m.group(2))
    else:
        tokens = re.findall(r"[A-Za-zÀ-ž]+", message.lower())
        cues = {"of", "whole", "all", "in", "for", "during", "cały", "caly", "ganzen", "ganz", "im"}
        named = next((t for i, t in enumerate(tokens) if t in MONTHS and i > 0 and tokens[i - 1] in cues), None)
        if named is None:
            return None
        month, first, last = MONTHS[named], 1, None
    year = as_of.year
    end_day = last or calendar.monthrange(year, month)[1]
    if date(year, month, end_day) < as_of:
        year += 1
        end_day = last or calendar.monthrange(year, month)[1]
    return date(year, month, first).isoformat(), date(year, month, end_day).isoformat()


def _evidence(results: list[Any]) -> list[dict[str, Any]]:
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
    text = message.lower()
    period = _closed_period(message, _as_of(conn, company))
    if period and re.search(r"closed|close|zamkni|geschlossen|holiday|urlaub|wakacje", text):
        args = {"label": message.strip()[:80], "date_from": period[0], "date_to": period[1], "effect": "no_variable_flows"}
        result = add_forecast_event(conn, company, **args)
        answer = f"Noted: closed {short_date(period[0])} to {short_date(period[1])} {period[0][:4]}. It is in the forecast as your event."
        if result["min_balance"]:
            low = result["min_balance"]
            answer += f" The lowest balance is now {liquidity.signed_amount(low['amount'])} on {short_date(low['date'])}."
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
            answer = (f"No gap is forecast: the lowest balance is {liquidity.signed_amount(low['amount'])} "
                      f"on {short_date(low['date'])}.")
        else:
            alert = facts["alert"]
            reasons = "; ".join(liquidity.reasons(facts))
            answer = (f"The accounts go below zero from {short_date(alert['date_from'])} and reach "
                      f"{liquidity.signed_amount(low['amount'])} on {short_date(low['date'])}. Main reasons: {reasons}.")
        g = tools.get_forecast(conn, company)
        evidence = _evidence([g]) + [e for e in _component_evidence(conn, forecast["id"]) if e]
        open_credit_lines = Store(conn).list("recommendation", company_id=company, type="credit_line", status=["new", "seen"])
        if open_credit_lines:
            answer += f" Proposed fix in your inbox: {open_credit_lines[0]['title']}."
            evidence.append({"kind": "recommendation", "id": open_credit_lines[0]["id"], "label": open_credit_lines[0]["title"],
                             "url": f"/recommendations/{open_credit_lines[0]['id']}"})
        return answer, evidence, [{"tool": "get_forecast", "arguments": {}, "duration_ms": 0}], None, None

    if re.search(r"\bowe|owes|owing|receivable|clients?\b|late pay", text):
        result = get_clients(conn, company)
        t = result["totals"]
        late = [(c["name"].replace(" (SAMPLE)", ""), i) for c in result["clients"] for i in c["late_invoices"]]
        answer = f"Clients owe you {fmt_money(t['open_base'])}."
        answer += (" " + f"{fmt_money(t['late_base'])} of it is late: " + "; ".join(
            f"{name} ({fmt_money(i['amount'])}, {i['days_late']} days late)" for name, i in late[:3]) + ".") if late else " Nothing is late."
        return answer, _evidence([result]), [{"tool": "get_clients", "arguments": {}, "duration_ms": 0}], None, None

    if re.search(r"cost|spend|spent|expens", text):
        result = get_month_costs(conn, company)
        change = Decimal(result["change"]["amount"])
        moved = [r for r in result["by_category"] if Decimal(r["change"]["amount"]) != 0][:3]
        answer = (f"Costs in {result['month']} so far: {fmt_money(result['costs'])}, "
                  f"{fmt_money({'amount': str(abs(change)), 'currency': result['change']['currency']})} "
                  f"{'more' if change > 0 else 'less'} than in {result['month_before']}.")
        if moved:
            answer += " Biggest changes: " + "; ".join(
                f"{r['category'].replace('_', ' ')} {'+' if Decimal(r['change']['amount']) > 0 else '-'}"
                f"{fmt_money({'amount': str(abs(Decimal(r['change']['amount']))), 'currency': r['change']['currency']})}" for r in moved) + "."
        return answer, _evidence([result]), [{"tool": "get_month_costs", "arguments": {}, "duration_ms": 0}], None, None

    if re.search(r"bonus|afford|stać|leisten", text):
        forecast = tools.latest_forecast(conn, company)
        if not forecast:
            return "There is no forecast yet.", [], [], None, None
        low, buffer = forecast["min_balance"], forecast.get("safety_buffer")
        room = Decimal(low["amount"]["amount"]) - Decimal(buffer["amount"] if buffer else "0")
        if room > 0:
            answer = (f"Yes, up to about {fmt_money({'amount': str(room), 'currency': low['amount']['currency']})}: the lowest expected "
                      f"balance is {liquidity.signed_amount(low['amount'])} on {short_date(low['date'])}"
                      + (f", and your safety buffer is {fmt_money(buffer)}." if buffer else "."))
        else:
            answer = (f"Not now: the lowest expected balance is {liquidity.signed_amount(low['amount'])} on {short_date(low['date'])}"
                      + (f", below your safety buffer of {fmt_money(buffer)}." if buffer else ".")
                      + (f" After {short_date(forecast['alerts'][0]['date_to'])} it is back above zero." if forecast.get("alerts") and forecast["alerts"][0].get("date_to") else ""))
        g = tools.get_forecast(conn, company)
        return answer, _evidence([g]), [{"tool": "get_forecast", "arguments": {}, "duration_ms": 0}], None, None

    if re.search(r"cash|balance|how much|money|ile|wie viel|saldo", text):
        result = get_cash_position(conn, company)
        answer = f"You have {fmt_money(result['total_liquidity_base'])} of company cash today."
        return answer, _evidence([result]), [{"tool": "get_cash_position", "arguments": {}, "duration_ms": 0}], None, None

    return ("I can answer about your cash and its forecast, what clients owe, costs by month, your to-dos, and note future "
            "events such as closed days. Try one of the suggested questions."), [], [], None, None


def _reply(session_id: str, company: str, text: str, **fields: Any) -> dict[str, Any]:
    return {"session_id": session_id, "answer": text, "evidence": [], "table": None, "tool_calls": [],
            "created_recommendation_id": None, "guardrail": None, "trace_id": None,
            "suggested_questions": SUGGESTED.get(company, SUGGESTED["co_borsuk"])} | fields


def answer(conn: psycopg.Connection, company: str, message: str, session_id: str | None, model: Any) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    created = guardrail = table = None
    results: list[Any] = []
    text = evidence = None
    session_id = session_id or f"chat_{uuid.uuid4().hex[:10]}"
    trace_id = None
    verdict = guardrails.check(message, agent="chat", company_id=company, session_id=session_id)
    message = verdict.text
    if verdict.blocked:
        remember(conn, session_id, company, message, guardrails.REFUSAL)
        return _reply(session_id, company, guardrails.REFUSAL, guardrail=verdict.note())
    if not verdict.model_allowed:
        model = None
    if model is not None:
        with tracing.span("chat.turn", {"message": message, "session_id": session_id}) as step:
            tracing.tag(agent="chat", company_id=company, session_id=session_id)
            trace_id = tracing.trace_id()
            messages = [{"role": "system", "content": SYSTEM}, *history(conn, session_id, company),
                        {"role": "user", "content": message}]
            result, results = run_tool_loop(model, conn, company, messages, CHAT_TOOLS, FINAL_SCHEMA, trace=trace)
            for r in results:
                if isinstance(r, dict) and r.get("recommendation_id") and any(t["tool"] == "request_action" for t in trace):
                    created, guardrail = r["recommendation_id"], GUARDRAIL_MONEY
            if result and not unexpected_numbers([result["answer"]], [results, message]):
                text, evidence = result["answer"], _evidence(results)
                sql = next((r for r in reversed(results) if isinstance(r, dict) and "columns" in r), None)
                if sql:
                    table = {"columns": sql["columns"], "rows": sql["rows"], "sql": sql["sql"]}
                    evidence.append({"kind": "sql", "id": "q_chat", "label": "The query behind the table", "excerpt": sql["sql"]})
                for r in results:
                    if isinstance(r, dict) and r.get("forecast_id"):
                        evidence += [e for e in _component_evidence(conn, r["forecast_id"]) if e not in evidence]
            outcome = "accepted" if text is not None else "no_answer" if not result else "rejected_numbers"
            tracing.tag(outcome=outcome, created_recommendation_id=created)
            tracing.outputs(step, {"outcome": outcome, "answer": text, "tool_calls": trace,
                                   "created_recommendation_id": created})
    if text is None and created:
        card = Store(conn).get("recommendation", created) or {}
        text = (f"I cannot move money from the chat. I put this in your inbox: \"{card.get('title', 'your request')}\". "
                "It runs only after you approve it, in simulation.")
        evidence = _evidence(results)
    if text is None:
        text, evidence, fallback_trace, fallback_created, fallback_guardrail = deterministic(conn, company, message)
        trace = trace or fallback_trace
        created = created or fallback_created
        guardrail = guardrail or fallback_guardrail
    remember(conn, session_id, company, message, text)
    return _reply(session_id, company, text, evidence=evidence or [], table=table, tool_calls=trace,
                  created_recommendation_id=created, guardrail=guardrail or verdict.note(), trace_id=trace_id)
