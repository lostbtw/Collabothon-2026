"""One reminder card per late client invoice; the e-mail is only a simulated draft after approval."""
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from backend.agents import tools
from backend.agents.text import fmt_money, short_date
from backend.api import owner
from backend.api.recommendations import save_recommendation
from backend.db.store import Store


def _month_of(conn: psycopg.Connection, company: str) -> str:
    return str(conn.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0])[:7]


def chase_late_clients(conn: psycopg.Connection, company: str, at: str | None = None) -> list[str]:
    late_days = owner.settings(conn, company)["alerts"]["late_client_days"]
    s = Store(conn)
    open_for = {r.get("subject", {}).get("id") for r in s.list("recommendation", company_id=company, type="chase_receivable",
                                                               status=["new", "seen"])}
    data = owner.clients(conn, company, _month_of(conn, company), persist_delays=False)
    created = []
    for client in data["items"]:
        name = client["name"].replace(" (SAMPLE)", "")
        for invoice in client["open_invoices"]:
            if invoice["days_late"] <= late_days or invoice["document_id"] in open_for:
                continue
            number = invoice["number"] or invoice["document_id"]
            habit = client["typical_payment_delay_days"]
            why = [f"Invoice {number} for {fmt_money(invoice['gross'])} was due on {short_date(invoice['due_date'])} "
                   f"and is {invoice['days_late']} days late"]
            if habit:
                why.append(f"{name} usually pays {habit} days late; a reminder can bring the money in sooner")
            card = {
                "id": f"rec_chase_{invoice['document_id']}",
                "company_id": company, "agent": "liquidity", "type": "chase_receivable",
                "title": f"Remind {name} to pay",
                "summary": f"Invoice {number} ({fmt_money(invoice['gross'])}) is {invoice['days_late']} days late. "
                           "Ordo writes a friendly reminder; you read it before it is sent.",
                "control_level": "approval_required", "execution_mode": "simulated", "status": "new",
                "severity": "warning", "created_at": at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "explanation": {"why": why, "confidence": 0.9,
                                "generated_by": {"numbers": "finance-engine", "wording": "template", "trace_id": None}},
                "evidence": [{"kind": "document", "id": invoice["document_id"], "label": f"Invoice {number}",
                              "url": f"/documents/{invoice['document_id']}"}],
                "proposed_action": {"kind": "send_email_draft",
                                    "params": {"to": name, "subject": f"Invoice {number}", "document_id": invoice["document_id"]},
                                    "preview": "SIMULATED: the reminder is drafted in Ordo. No e-mail leaves the app in this build."},
                "impact": {"cost": {"amount": "0.00", "currency": invoice["gross_base"]["currency"]}},
                "subject": {"kind": "document", "id": invoice["document_id"], "label": f"Invoice {number}"},
                "approval_id": None,
            }
            if save_recommendation(conn, card):
                created.append(card["id"])
    return created


ASK_SOONER = re.compile(r"\b(remind\w*|earlier|sooner|chase|ask|request\w*|faster|early)\b", re.I)


def reminder_for(conn: psycopg.Connection, company: str, request: str, *, force: bool = False,
                 at: str | None = None) -> dict[str, Any] | None:
    """The chat's "ask <client> to pay earlier": a reminder card with the drafted e-mail for that client's open
    invoice, late or not. None when no client with an expected payment is named (or it is not a reminder request)."""
    if not force and not ASK_SOONER.search(request):
        return None
    words = request.lower()
    items = [i for i in tools.list_overdue_receivables(conn, company)["items"]
             if i.get("client") and i["client"].lower() in words and i.get("document_id")]
    if not items:
        return None
    item = min(items, key=lambda i: i.get("expected_date") or "9999")
    s = Store(conn)
    for open_card in s.list("recommendation", company_id=company, type="chase_receivable", status=["new", "seen"]):
        if (open_card.get("subject") or {}).get("id") == item["document_id"]:
            return open_card

    document = s.get("document", item["document_id"]) or {}
    label_number = item["label"].split()[1] if item["label"].startswith("Invoice ") else None
    number = document.get("number") or label_number or item["document_id"]
    name = item["client"]
    gross = (document.get("totals") or {}).get("gross") or document.get("gross")
    amount = fmt_money(gross) if gross else fmt_money(item["amount_base"])
    due = document.get("due_date")
    today = str(conn.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0])
    company_name = conn.execute("select name from companies where id = %s", (company,)).fetchone()[0].replace(" (SAMPLE)", "")
    forecast = tools.get_forecast(conn, company)
    gap = sorted((a for a in forecast.get("alerts", []) if a["type"] in ("cash_gap", "below_buffer")),
                 key=lambda a: a["date_from"])
    pay_by = gap[0]["date_from"] if gap else None

    why = [f"{item['label']} is expected on {short_date(item['expected_date'])}"
           + (f" ({item['schedule']})" if item.get("schedule") else "")]
    if gap:
        why.append(f"The forecast falls below the safety buffer on {short_date(gap[0]['date_from'])}, lowest "
                   f"{fmt_money(forecast['min_balance']['amount'], cents=False)} on {short_date(forecast['min_balance']['date'])}")
    if due and due < today:
        timing = f"was due on {short_date(due)}"
    elif due:
        timing = f"is due on {short_date(due)}"
    else:
        timing = f"is expected on {short_date(item['expected_date'])}"
    ask = f"Could you pay it by {short_date(pay_by)}?" if pay_by else "Could you pay it in the next few days?"
    email = (f"To: {name}\nSubject: Invoice {number}\n\nHello {name} team,\n\nour invoice {number} for {amount} {timing}. "
             f"{ask} It would help us a lot this month.\n\nThank you,\n{company_name}")
    card = {
        "id": f"rec_chase_{item['document_id']}_{uuid.uuid4().hex[:6]}",
        "company_id": company, "agent": "liquidity", "type": "chase_receivable",
        "title": f"Ask {name} to pay invoice {number} earlier",
        "summary": f"Invoice {number} ({amount}) {timing}. Ordo drafted a friendly e-mail asking {name} to pay sooner; "
                   "you read it before it is sent.",
        "control_level": "approval_required", "execution_mode": "simulated", "status": "new",
        "severity": "warning", "created_at": at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "explanation": {"why": why, "confidence": 0.9,
                        "generated_by": {"numbers": "finance-engine", "wording": "template", "trace_id": None}},
        "evidence": [{"kind": "document", "id": item["document_id"], "label": f"Invoice {number}",
                      "url": f"/documents/{item['document_id']}"}],
        "proposed_action": {"kind": "send_email_draft",
                            "params": {"to": name, "subject": f"Invoice {number}", "document_id": item["document_id"],
                                       "body": email},
                            "preview": f"SIMULATED: sends this e-mail from Ordo. No e-mail leaves the app in this build.\n\n{email}"},
        "impact": {"cost": {"amount": "0.00", "currency": item["amount_base"]["currency"]}},
        "subject": {"kind": "document", "id": item["document_id"], "label": f"Invoice {number}"},
        "approval_id": None,
    }
    return card if save_recommendation(conn, card) else None


def on_forecast_updated(conn: psycopg.Connection, event: dict[str, Any]) -> list[str]:
    return chase_late_clients(conn, event["company_id"], event.get("occurred_at"))
