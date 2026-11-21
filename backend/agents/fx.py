"""FX Shield: the model judges each foreign-currency invoice ignore / inform / hedge against the company's own figures."""
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from backend import settings
from backend.agents.llm import default_client, run_tool_loop
from backend.agents.numbers import unexpected_numbers
from backend.agents.text import fmt_money, short_date
from backend.agents.tools import _schema
from backend.api.ports import finance_engine
from backend.api.recommendations import save_recommendation
from backend.db.events import new_event, publish
from backend.db.store import Store

_DEFAULT = object()
OPEN = ("new", "seen")
FINAL = ("approved", "executed_simulated")
ILLUSTRATIVE = ("Forward and option prices are illustrative, not an offer; the interest-rate difference between the "
                "currencies is ignored")
HISTORY = "History is not a forecast: a move larger than any in the last three years is possible"
JUDGED = ("FX Shield's model judged this invoice against your company's own figures; there is no fixed threshold. "
          "A negative cash balance counts as a reason to hedge, not as one on its own")
RULE_NATURAL = {"kind": "rule", "id": "FX-RULE-02",
                "label": "Invoices and balances in the same currency offset each other before anything is bought"}
METHOD = {"kind": "rule", "id": "FX-METHOD-01",
          "label": "Expected shortfall over the last three years of NBP rates, judged against the company's own figures"}


def m(value: dict[str, str]) -> str:
    return fmt_money(value, cents=False)


def signed(value: dict[str, str]) -> str:
    return ("-" if Decimal(value["amount"]) < 0 else "+") + m(value)


def signature(a: dict[str, Any]) -> str:
    keys = ("status", "expected_shortfall", "net_amount", "expected_cash_date", "spot")
    return hashlib.sha1(json.dumps({k: a.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()[:10]


def card_id(a: dict[str, Any]) -> str:
    return f"rec_fx_{re.sub(r'[^A-Za-z0-9_]', '_', a['document_id'])}_{signature(a)}"


def _document(a: dict[str, Any]) -> dict[str, str]:
    return {"kind": "document", "id": a["document_id"], "label": a["label"], "url": f"/documents/{a['document_id']}"}


def _rates(a: dict[str, Any]) -> dict[str, str]:
    cur, base = a["amount"]["currency"], a["value_today_base"]["currency"]
    return {"kind": "fx_rate", "id": f"nbp_{cur.lower()}_{a['history_first']}_{a['history_last']}",
            "label": f"{cur}/{base} daily rates, NBP table A, {a['history_days']} days", "url": f"/fx/history?currency={cur}"}


def compared(a: dict[str, Any]) -> str:
    ref = a.get("chosen")
    return f", {ref['loss_share_percent']}% of {ref['label']} ({m(ref['amount'])})" if ref else ""


def cash_sentence(a: dict[str, Any]) -> str:
    if not a.get("bad_case_takes_balance_below_zero"):
        return ""
    low = a["lowest_balance_after_payment_with_bad_case"]
    return (f" It would push your cash forecast {'further ' if a['already_negative_after_payment'] else ''}below zero: "
            f"lowest balance {signed(low['balance'])} on {short_date(low['date'])}.")


def calculation(a: dict[str, Any]) -> list[dict[str, Any]]:
    cur, base = a["amount"]["currency"], a["value_today_base"]["currency"]
    h, company = a["hedge"], a["company"]
    rows = [{"label": "Invoice value today", "value": m(a["value_today_base"]),
             "formula": f"{m(a['net_amount'])} x {a['spot']} (the forecast's rate)"}]
    if Decimal(a["covered"]["amount"]) > 0:
        rows.append({"label": f"Already covered in {cur}", "value": m(a["covered"]),
                     "formula": f"{cur} invoices on the other side expected at about the same time"
                                + (" and the balance you hold" if a["direction"] == "payable" else "")})
    rows += [
        {"label": "Scenarios", "value": str(a["scenarios"]),
         "formula": f"every {a['horizon_days']}-day change of {cur}/{base} from {a['history_first']} to "
                    f"{a['history_last']}, applied to today's rate"},
        {"label": "Average result", "value": signed(a["average_result"]),
         "formula": "mean over all scenarios: close to zero, so not a useful risk measure"},
        {"label": "Bad case (95th percentile)", "value": signed(a["bad_case_p95"]), "formula": "loss exceeded in 5% of scenarios"},
        {"label": "Expected shortfall", "value": signed(a["expected_shortfall"]),
         "formula": "average loss in the worst 10% of scenarios"},
        {"label": "Good case (95th percentile)", "value": signed(a["good_case_p95"]), "formula": "gain exceeded in 5% of scenarios"},
    ]
    weakest = next((r for r in company["references"] if r["id"] == "money_in_weakest_month"), None)
    if weakest and company.get("money_in_strongest_month"):
        rows.append({"label": "Money in per month", "value": f"{m(weakest['amount'])} to {m(company['money_in_strongest_month'])}",
                     "formula": f"weakest to strongest of the last {len(company['months'])} full months: it varies"})
    if a.get("chosen"):
        ref = a["chosen"]
        rows.append({"label": "Compared with", "value": f"{ref['loss_share_percent']}%",
                     "formula": f"{m(a['expected_shortfall'])} / {m(ref['amount'])}, {ref['label']} (chosen by FX Shield's model)"})
    after, bad = a["lowest_balance_after_payment"], a["lowest_balance_after_payment_with_bad_case"]
    rows += [
        {"label": "Lowest forecast balance after payment", "value": signed(after["balance"]),
         "formula": f"on {short_date(after['date'])}, the cash forecast from the payment date on"},
        {"label": "... with the bad case", "value": signed(bad["balance"]),
         "formula": "the same, with the expected shortfall taken off"},
        {"label": "Cost of a forward", "value": m(h["forward_cost"]),
         "formula": f"{m(h['notional'])} hedged ({h['ratio']} of the amount), illustrative bank margin"},
        {"label": "With the forward you " + ("receive" if a["direction"] == "receivable" else "pay"),
         "value": m(h["with_forward"]), "formula": f"{m(h['notional'])} x {h['forward_rate']}, whatever the rate does"},
    ]
    return rows


def _base(company: str, a: dict[str, Any], at: str, **fields: Any) -> dict[str, Any]:
    explanation = fields.pop("explanation")
    explanation.update({"confidence": 0.8,
                        "generated_by": {"numbers": "finance-engine", "wording": settings.llm_model(), "trace_id": None}})
    return {"id": a.get("card_id") or card_id(a), "company_id": company, "agent": "fx", "status": "new",
            "created_at": at, "subject": {"kind": "document", "id": a["document_id"], "label": a["label"]},
            "approval_id": None, "explanation": explanation, **fields}


def hedge_card(company: str, a: dict[str, Any], at: str) -> dict[str, Any]:
    h, cur = a["hedge"], a["amount"]["currency"]
    receivable = a["direction"] == "receivable"
    summary = (f"{m(a['amount'])} {'to be paid to you' if receivable else 'to pay'} on "
               f"{short_date(a['expected_cash_date'])}, in {a['horizon_days']} days. If the {cur} "
               f"{'falls' if receivable else 'rises'} the way it did in the worst tenth of the last three years, "
               f"you lose about {m(a['expected_shortfall'])}{compared(a)}.{cash_sentence(a)} Fixing the rate today "
               f"costs about {m(h['forward_cost'])}.")
    assumptions = [JUDGED]
    if h["ratio"] != "1.0":
        assumptions.append(f"The client pays late on average: {h['ratio']} of the amount is hedged, on the expected date")
    assumptions += [ILLUSTRATIVE, HISTORY]
    preview = (f"SIMULATED: books a forward to {'sell' if receivable else 'buy'} {m(h['notional'])} for "
               f"{m(h['with_forward'])} on {short_date(h['value_date'])} at Commerzbank. No real bank is contacted.")
    zero = {"amount": "0.00", "currency": a["value_today_base"]["currency"]}
    return _base(
        company, a, at, type="fx_hedge", title=f"Fix the exchange rate for {a['label']}",
        summary=summary, control_level="approval_required", execution_mode="simulated", severity="warning",
        valid_until=f"{(date.fromisoformat(at[:10]) + timedelta(days=3)).isoformat()}T16:00:00Z",
        explanation={
            "why": [a["decided_because"], f"The invoice is in {cur} and the money moves in {a['horizon_days']} days",
                    f"Fixing the rate costs about {m(h['forward_cost'])}"],
            "calculation": calculation(a),
            "alternatives": [
                {"label": "Do nothing", "pros": "Free; you keep the gain if the rate moves your way",
                 "cons": "In a bad case the loss above is yours", "cost": zero},
                {"label": "Option instead of forward", "pros": "Protects the bad case and keeps the good case",
                 "cons": "Costs about four times more", "cost": h["option_cost"]}],
            "assumptions": assumptions},
        evidence=[_document(a), _rates(a), METHOD],
        proposed_action={"kind": "book_fx_forward",
                         "params": {"sell_currency": h["sell_currency"], "buy_currency": h["buy_currency"],
                                    "notional": h["notional"], "rate": h["forward_rate"], "value_date": h["value_date"],
                                    "hedge_ratio": float(h["ratio"]), "bank": "Commerzbank"},
                         "preview": preview},
        impact={"cash_effect": None, "cost": h["forward_cost"], "min_balance_before": None, "min_balance_after": None,
                "scenario_forecast_id": None})


def no_hedge_card(company: str, a: dict[str, Any], at: str) -> dict[str, Any]:
    h = a["hedge"]
    summary = (f"{m(a['amount'])}, expected on {short_date(a['expected_cash_date'])} ({a['horizon_days']} days). "
               f"Even in a bad case the exchange rate costs about {m(a['expected_shortfall'])}{compared(a)}."
               f"{cash_sentence(a)} Hedging would not pay off.")
    return _base(
        company, a, at, type="info", title=f"No need to hedge {a['label']}", summary=summary,
        control_level="recommendation", execution_mode="none", severity="info", valid_until=None,
        explanation={
            "why": [a["decided_because"], f"Based on {a['scenarios']} scenarios from three years of NBP rates"],
            "calculation": calculation(a),
            "alternatives": [{"label": "Hedge anyway with a forward", "pros": "Certainty",
                              "cons": f"Costs about {m(h['forward_cost'])} to remove a risk of about "
                                      f"{m(a['expected_shortfall'])}", "cost": h["forward_cost"]}],
            "assumptions": [JUDGED, ILLUSTRATIVE, HISTORY]},
        evidence=[_document(a), _rates(a), METHOD], proposed_action=None, impact=None)


def natural_card(company: str, a: dict[str, Any], at: str) -> dict[str, Any]:
    cur = a["amount"]["currency"]
    summary = (f"{m(a['covered'])} of the {m(a['amount'])} is matched by {cur} you pay out, receive or hold at about "
               f"the same time, so a rate move on one side is cancelled by the other. Nothing to buy.")
    return _base(
        company, a, at, type="info", title=f"{a['label']} is already covered in {cur}", summary=summary,
        control_level="recommendation", execution_mode="none", severity="info", valid_until=None,
        explanation={
            "why": [a["decided_because"], "Using what you already have costs nothing"],
            "calculation": [
                {"label": "Invoice", "value": m(a["amount"]), "formula": None},
                {"label": f"Covered in {cur}", "value": m(a["covered"]),
                 "formula": "invoices on the other side expected at about the same time"
                            + (" and the balance you hold" if a["direction"] == "payable" else "")},
                {"label": "Left exposed", "value": m(a["net_amount"]), "formula": "too little to be worth a hedge"}],
            "alternatives": [], "assumptions": [JUDGED, HISTORY]},
        evidence=[_document(a), RULE_NATURAL], proposed_action=None, impact=None)


def ignored_card(company: str, a: dict[str, Any], at: str) -> dict[str, Any]:
    return _base(
        company, a, at, type="info", title=f"Not worth your attention: {a['label']}", status="expired",
        summary=f"FX Shield looked at {m(a['amount'])} expected on {short_date(a['expected_cash_date'])}. "
                f"{a['decided_because']}",
        control_level="recommendation", execution_mode="none", severity="info", valid_until=None,
        explanation={"why": [a["decided_because"]], "calculation": [], "alternatives": [], "assumptions": [JUDGED]},
        evidence=[_document(a), METHOD], proposed_action=None, impact=None)


FINAL_SCHEMA = {"type": "object", "required": ["action", "reference", "reason"], "additionalProperties": False,
                "properties": {"action": {"type": "string", "enum": ["hedge", "inform", "ignore"]},
                               "reference": {"type": "string"},
                               "reason": {"type": "string", "minLength": 20, "maxLength": 400}}}
SYSTEM = (
    "You are FX Shield, the currency-risk agent of Ordo, an autonomous CFO for a small company. You look at one open "
    "foreign-currency invoice at a time, with the company's own figures, and decide as a careful CFO would for this "
    "company: (1) does this exposure deserve the owner's attention at all, or is it too small for this company to "
    'matter ("ignore")? (2) if it does, is the possible loss critical enough to propose fixing the rate ("hedge"), '
    'or should the owner only know about it ("inform")? (3) which reference amount of the company the loss is best '
    'compared with ("reference": one id from loss_vs_references, or "none" when that list is empty). '
    "There is no profit on a single invoice or purchase and there is no fixed threshold: judge against the company. "
    "Its money in varies a lot from month to month (see months), so do not rely on one month or on an average alone. "
    "A negative cash balance is undesirable but not critical, because a credit line covers it: count it as a reason "
    "to hedge when the loss would push or deepen it, never as a reason on its own. Never propose a hedge whose cost "
    "is not clearly below the expected shortfall. An invoice whose status is naturally_hedged is already covered: "
    'answer "inform" or "ignore". Call get_fx_case if you need the numbers again. Copy numbers exactly from the facts '
    "or leave them out; never compute, round or invent a number. Answer with JSON only: "
    '{"action": "hedge" or "inform" or "ignore", "reference": "<id>", "reason": "one or two plain sentences for the owner"}.')
CASE_FIELDS = ("document_id", "label", "direction", "status", "amount", "covered", "net_amount", "value_today_base",
               "expected_cash_date", "horizon_days", "scenarios", "bad_case_p95", "expected_shortfall", "good_case_p95",
               "loss_vs_references", "lowest_balance_after_payment", "lowest_balance_after_payment_with_bad_case",
               "already_negative_after_payment", "bad_case_takes_balance_below_zero", "company", "hedge")


def case_facts(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a[k] for k in CASE_FIELDS if k in a}


def get_fx_case(conn: psycopg.Connection, company: str, document_id: str) -> dict[str, Any]:
    engine = finance_engine()
    for a in engine.fx_assessments(conn, company) if engine else []:
        if a["document_id"] == document_id:
            return case_facts(a)
    return {"error": f"no open foreign-currency invoice {document_id}"}


TOOLS = {"get_fx_case": (_schema("get_fx_case", "FX Shield's facts for one open foreign-currency invoice: value, "
                                 "scenarios, bad case, expected shortfall, the loss against the company's reference "
                                 "amounts, its money in and out month by month, the cash forecast after the payment "
                                 "date with and without the bad case, the forward's cost",
                                 {"document_id": {"type": "string"}}), get_fx_case)}


def judge(model: Any, conn: psycopg.Connection, company: str, a: dict[str, Any],
          others: list[dict[str, Any]]) -> dict[str, str] | None:
    facts = case_facts(a)
    context = [{k: o.get(k) for k in ("document_id", "label", "status", "value_today_base", "expected_shortfall")}
               for o in others if o["document_id"] != a["document_id"]]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Invoice {a['document_id']}. Facts from the finance engine: "
                                            f"{json.dumps(facts)}. The company's other open foreign-currency invoices: "
                                            f"{json.dumps(context)}"}]
    answer, results = run_tool_loop(model, conn, company, messages, TOOLS, FINAL_SCHEMA)
    if answer is None:
        return None
    references = {r["id"] for r in a["loss_vs_references"]}
    if answer["reference"] not in (references or {"none"}):
        return None
    if a["status"] == "naturally_hedged" and answer["action"] == "hedge":
        return None
    if unexpected_numbers([answer["reason"]], [results, facts, context, a["label"]]):
        return None
    return answer


def on_forecast_updated(conn: psycopg.Connection, event: dict[str, Any], model: Any = _DEFAULT) -> list[str]:
    engine = finance_engine()
    if engine is None or not hasattr(engine, "fx_assessments"):
        return []
    company = event["company_id"]
    s = Store(conn)
    created = []
    assessments = engine.fx_assessments(conn, company)
    for a in assessments:
        if a["status"] == "hedged":
            continue
        mine = [r for r in s.list("recommendation", company_id=company, agent="fx")
                if (r.get("subject") or {}).get("id") == a["document_id"]]
        if any(r["status"] in FINAL for r in mine):
            continue  # the owner approved a hedge for this invoice: that decision stands
        cid = card_id(a)
        if any(r["id"] == cid for r in mine):
            continue
        if model is _DEFAULT:
            model = default_client()
        if model is None:
            return created
        answer = judge(model, conn, company, a, assessments)
        if answer is None:
            continue
        chosen = next((r for r in a["loss_vs_references"] if r["id"] == answer["reference"]), None)
        card_input = {**a, "card_id": cid, "decided_because": answer["reason"], "chosen": chosen}
        for old in (r for r in mine if r["status"] in OPEN):
            s.put("recommendation", {**old, "status": "superseded"})
            publish(conn, new_event("recommendation.status_changed", company,
                                    {"recommendation_id": old["id"], "status": "superseded"}, producer="agents"))
        if answer["action"] == "ignore":
            if s.add("recommendation", ignored_card(company, card_input, event["occurred_at"]), company_id=company):
                created.append(cid)
            continue
        if a["status"] == "naturally_hedged":
            card = natural_card(company, card_input, event["occurred_at"])
        elif answer["action"] == "hedge":
            card = hedge_card(company, card_input, event["occurred_at"])
        else:
            card = no_hedge_card(company, card_input, event["occurred_at"])
        if save_recommendation(conn, card):
            created.append(card["id"])
    return created
