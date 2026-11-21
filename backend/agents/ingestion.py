"""Inbox cards from Matches and upcoming tax payments, template text only."""
import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from backend.agents.text import fmt_money, ordinal_day, short_date
from backend.api.recommendations import save_recommendation
from backend.db.events import new_event, publish
from backend.db.store import Store

GENERATED_BY = {"numbers": "finance-engine", "wording": "template", "trace_id": None}
ACCOUNTANT = "Confirm with your accountant."
RULE_LABELS = {
    "PL-VAT-01": "VAT deduction needs an invoice issued to the company",
    "PL-VAT-02": "Receipt up to 450 PLN with the company tax id is a simplified invoice",
    "PL-VAT-03": "Foreign B2B service: reverse charge, VAT neutral",
    "PL-COST-01": "Cost booked gross when VAT cannot be deducted",
    "PL-REIMB-01": "Reimbursing a documented cost is not salary",
    "PL-PRIV-01": "Private purchases are not company costs",
    "PL-FX-01": "Foreign-currency costs use the NBP rate of the previous business day",
    "DQ-01": "Data quality check",
}


def _rec_id(kind: str, subject_id: str) -> str:
    return f"rec_{kind}_{subject_id}"


def _link(kind: str, id: str, label: str) -> dict[str, str]:
    paths = {"document": "documents", "match": "matches", "transaction": "transactions", "forecast": "forecast"}
    link = {"kind": kind, "id": id, "label": label}
    if kind in paths:
        link["url"] = f"/{paths[kind]}/{id}"
    return link


def _pay_run(issued: str) -> str:
    d = date.fromisoformat(issued[:10])
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last.isoformat()


def _what(document: dict[str, Any]) -> str:
    lines = document.get("lines") or []
    if lines and lines[0].get("description"):
        return lines[0]["description"]
    return f"the {document.get('seller', {}).get('name', 'purchase')} {document.get('doc_type', 'document')}"


def _candidates(s: Store, company: str, document: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    gross = document.get("totals", {}).get("gross_base")
    if not gross:
        return []
    target = abs(Decimal(gross["amount"]))
    issued = date.fromisoformat((document.get("issue_date") or "1970-01-01")[:10])
    found = []
    for t in s.list("transaction", company_id=company, match_status=["unmatched", "suggested"]):
        if t["id"] == match.get("transaction_id") or t["amount_base"]["currency"] != gross["currency"]:
            continue
        amount = abs(Decimal(t["amount_base"]["amount"]))
        if target and abs(amount - target) / target <= Decimal("0.045"):
            found.append((abs((date.fromisoformat(t["booking_date"]) - issued).days), t))
    return [t for _, t in sorted(found, key=lambda x: x[0])[:3]]


def _evidence(document: dict, match: dict) -> list[dict[str, str]]:
    seller = document.get("seller", {}).get("name", "Document")
    links = [_link("document", document["id"], f"{seller}, {fmt_money(document['totals']['gross'])}"),
             _link("match", match["id"], "Why we matched it this way")]
    if match.get("transaction_id"):
        links.append(_link("transaction", match["transaction_id"], "Bank line"))
    for rule in match["consequences"].get("rule_ids", []):
        links.append(_link("rule", rule, RULE_LABELS.get(rule, rule)))
    return links


def _base(company: str, kind: str, subject: dict, *, title: str, summary: str, control_level: str, execution_mode: str,
          severity: str, created_at: str, why: list[str], calculation: list[dict], confidence: float,
          evidence: list[dict], proposed_action: dict | None, alternatives: list[dict] | None = None,
          impact: dict | None = None) -> dict[str, Any]:
    return {
        "id": _rec_id(kind, subject["id"]),
        "company_id": company,
        "agent": "tax" if kind == "tax_reserve" else "ingestion",
        "type": kind,
        "title": title,
        "summary": summary,
        "control_level": control_level,
        "execution_mode": execution_mode,
        "status": "new",
        "severity": severity,
        "created_at": created_at,
        "valid_until": None,
        "explanation": {"why": why, "calculation": calculation, "alternatives": alternatives or [], "assumptions": [],
                        "confidence": confidence, "generated_by": GENERATED_BY},
        "evidence": evidence,
        "proposed_action": proposed_action,
        "impact": impact,
        "subject": subject,
        "approval_id": None,
    }


def recommendation_for_match(s: Store, company: str, match: dict[str, Any], document: dict[str, Any], at: str) -> dict[str, Any] | None:
    if match["status"] != "suggested":
        return None
    c = match["consequences"]
    rules = set(c.get("rule_ids", []))
    seller = document.get("seller", {}).get("name", "the seller")
    gross = document["totals"]["gross"]
    why = [r["detail"] for r in match.get("reasons", [])]
    score = match["score"]
    evidence = _evidence(document, match)
    match_subject = _link("match", match["id"], f"{seller}, {fmt_money(gross)}")
    match_subject.pop("url")
    common = dict(created_at=at, why=why, confidence=score, evidence=evidence)

    if match["paid_by"] == "employee_private" and c.get("reimbursement_owed"):
        person = c.get("reimbursement_to") or match.get("payer") or {}
        first = (person.get("name") or "the employee").split(" ")[0]
        owed = c["reimbursement_owed"]
        pay_on = _pay_run(document.get("issue_date") or at)
        calculation = [{"label": "Reimbursement", "value": fmt_money(owed), "formula": "gross amount on the document"}]
        summary = f"{first} paid {fmt_money(owed)} to {seller} privately and sent the document."
        if c.get("vat_lost"):
            calculation.append({"label": "VAT not recoverable", "value": fmt_money(c["vat_lost"]), "formula": None})
            summary += f" {fmt_money(c['vat_lost'])} of VAT cannot be recovered because the document has no company tax id."
        summary += " Paying it back as a reimbursement (not as salary) avoids income tax and social security on it. " + ACCOUNTANT
        subject = {"kind": "document", "id": document["id"], "label": f"{seller}, {fmt_money(gross)}"}
        return _base(
            company, "reimburse_employee", subject,
            title=f"Pay {first} back {fmt_money(owed)} for {_what(document)}",
            summary=summary, control_level="approval_required", execution_mode="simulated", severity="info",
            calculation=calculation,
            proposed_action={"kind": "create_payment_draft",
                             "params": {"to": person.get("person_id"), "amount": owed,
                                        "title": f"Reimbursement: {_what(document)}", "pay_on": pay_on},
                             "preview": f"SIMULATED: books the cost, records {fmt_money(owed)} owed to {first} and adds a "
                                        f"transfer draft to the {short_date(pay_on)} payment run in the Sandbox Bank."},
            impact={"cash_effect": {"amount": f"-{Decimal(owed['amount']):.2f}", "currency": owed["currency"]},
                    "cost": c.get("vat_lost")},
            **common)

    if "PL-PRIV-01" in rules or "possible_private" in document.get("flags", []):
        return _base(
            company, "mark_private", match_subject,
            title=f"Mark {seller} {fmt_money(gross)} as private?",
            summary=f"This purchase from {seller} looks private but was paid from the company account. "
                    f"If it is private, it is not a company cost. {ACCOUNTANT}",
            control_level="recommendation", execution_mode="none", severity="info", calculation=[],
            proposed_action=None, **common)

    if score < 0.55:
        return _base(
            company, "missing_document", match_subject,
            title=f"Which payment is {seller} {fmt_money(gross)}?",
            summary=f"We could not tie {seller} {fmt_money(gross)} to a bank line or a document with confidence.",
            control_level="recommendation", execution_mode="none", severity="warning", calculation=[],
            proposed_action=None, **common)

    if match["paid_by"] == "company_account" and c.get("vat_deductible") is False and score >= 0.90:
        lost = c.get("vat_lost") or c.get("vat_amount")
        return _base(
            company, "request_company_invoice", match_subject,
            title=f"Ask {seller} for an invoice to the company next time",
            summary=f"The document from {seller} has no company tax id"
                    + (f", so {fmt_money(lost)} of VAT cannot be deducted." if lost else ", so its VAT cannot be deducted.")
                    + f" {ACCOUNTANT}",
            control_level="recommendation", execution_mode="none", severity="info",
            calculation=[{"label": "VAT not deductible", "value": fmt_money(lost), "formula": None}] if lost else [],
            proposed_action=None, **common)

    alternatives = [{"label": f"Bank line {t['booking_date']} {fmt_money(t['amount_base'])} "
                              f"{t.get('counterparty_name_raw') or ''} ({t['id']})".replace("  ", " "),
                     "pros": None, "cons": None}
                    for t in _candidates(s, company, document, match)]
    paid = (f"the bank line {match['transaction_id']}" if match.get("transaction_id")
            else {"owner_private": "your private card", "employee_private": "an employee"}.get(match["paid_by"], "an unknown payer"))
    return _base(
        company, "confirm_match", match_subject,
        title=f"Confirm {seller} {fmt_money(gross)} was paid by {paid}",
        summary=(c.get("note") or f"{seller} {fmt_money(gross)} and {paid} look like the same purchase.")
                + f" Match confidence {score:.2f}.",
        control_level="approval_required", execution_mode="none", severity="info", calculation=[],
        proposed_action={"kind": "book_ledger_entries", "params": {"match_id": match["id"]},
                         "preview": "Books the entries this match calls for in your ledger."},
        alternatives=alternatives, **common)


def on_match_suggested(conn: psycopg.Connection, event: dict[str, Any]) -> str | None:
    s = Store(conn)
    match = s.get("match", event["payload"]["match_id"])
    if match is None:
        return None
    document = s.get("document", match["document_id"])
    if document is None:
        return None
    rec = recommendation_for_match(s, event["company_id"], match, document, event["occurred_at"])
    if rec is None:
        return None
    return rec["id"] if save_recommendation(conn, rec) else None


def on_forecast_updated(conn: psycopg.Connection, event: dict[str, Any]) -> list[str]:
    s = Store(conn)
    forecast = s.get("forecast", event["payload"]["forecast_id"])
    if forecast is None:
        return []
    created = []
    for comp in forecast["components"]:
        if comp["kind"] != "tax" or Decimal(comp["amount_base"]["amount"]) >= 0 or not comp.get("dates"):
            continue
        due = date.fromisoformat(comp["dates"][0])
        tax = comp["label"].split(" for ")[0].split(",")[0].strip()
        amount = {"amount": f"{abs(Decimal(comp['amount_base']['amount'])):.2f}", "currency": comp["amount_base"]["currency"]}
        subject = {"kind": "forecast_component", "id": comp["id"], "label": comp["label"]}
        evidence = [_link("forecast", forecast["id"], "Forecast"),
                    {"kind": "forecast_component", "id": comp["id"], "label": comp["label"],
                     "url": f"/forecast/{forecast['id']}#{comp['id']}"}, *comp.get("evidence", [])]
        rec = _base(
            event["company_id"], "tax_reserve", subject,
            title=f"Set aside {fmt_money(amount, cents=False)} for {tax} on the {ordinal_day(due)}",
            summary=f"{comp['label']}: {fmt_money(amount)} is due on {due.isoformat()}. Moving it to the tax pocket now "
                    f"keeps it from being spent.",
            control_level="approval_required", execution_mode="simulated", severity="warning",
            created_at=event["occurred_at"], why=[f"{comp['label']} ({comp.get('schedule') or 'due ' + due.isoformat()})"],
            calculation=[{"label": tax, "value": fmt_money(amount), "formula": comp.get("schedule")}],
            confidence=comp["confidence"], evidence=evidence,
            proposed_action={"kind": "move_to_tax_pocket", "params": {"amount": amount, "tax": tax, "due_date": due.isoformat()},
                             "preview": f"SIMULATED: moves {fmt_money(amount)} to the tax pocket in the Sandbox Bank."})
        if save_recommendation(conn, rec):
            created.append(rec["id"])
    supersede_stale_tax_cards(conn, event["company_id"], forecast)
    return created


def supersede_stale_tax_cards(conn: psycopg.Connection, company: str, forecast: dict[str, Any]) -> list[str]:
    """Open tax cards for a payment the forecast no longer has (an older engine run) leave the to-do."""
    current = {_rec_id("tax_reserve", c["id"]) for c in forecast["components"] if c["kind"] == "tax"}
    s = Store(conn)
    gone = []
    for old in s.list("recommendation", company_id=company, type="tax_reserve", status=["new", "seen"]):
        if old["id"] in current:
            continue
        s.put("recommendation", {**old, "status": "superseded"})
        publish(conn, new_event("recommendation.status_changed", company,
                                {"recommendation_id": old["id"], "status": "superseded"}, producer="agents"))
        gone.append(old["id"])
    return gone
