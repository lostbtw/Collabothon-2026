"""One reminder card per late client invoice; the e-mail is only a simulated draft after approval."""
from datetime import UTC, datetime
from typing import Any

import psycopg

from backend.agents.text import fmt_money, short_date
from backend.api import owner
from backend.api.recommendations import save_recommendation
from backend.db.store import Store


def _month_of(conn: psycopg.Connection, company: str) -> str:
    return str(conn.execute("select as_of_date from companies where id = %s", (company,)).fetchone()[0])[:7]


def chase_late_clients(conn: psycopg.Connection, company: str, at: str | None = None) -> list[str]:
    """Create the missing reminder cards. Returns the ids created."""
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


def on_forecast_updated(conn: psycopg.Connection, event: dict[str, Any]) -> list[str]:
    """Handler for `forecast.updated`: the forecast was recomputed, so open invoices may have become late."""
    return chase_late_clients(conn, event["company_id"], event.get("occurred_at"))
