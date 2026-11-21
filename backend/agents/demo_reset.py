"""`python -m backend demo-reset [company ...]`: puts the demo's to-do back in shape before a run (default co_borsuk).

- Open cards the chat made ("You asked: ..." notes and the chat's reminder e-mails) leave the to-do.
- Open tax cards for payments the latest forecast no longer has leave the to-do.
- When the forecast still has a cash gap and no credit-line card is open, a fresh one is added.

Approved, rejected and executed cards stay in the history; nothing is deleted. On the cluster:
    oc -n cfo-ai exec deploy/ordo-agents -- python -m backend demo-reset
"""
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from backend.agents import ingestion, liquidity, tools
from backend.api.recommendations import save_recommendation
from backend.db.events import new_event, publish
from backend.db.store import Store
from backend.settings import database_url

CHAT_REMINDER = re.compile(r"^rec_chase_.+_[0-9a-f]{6}$")


def _supersede(conn: psycopg.Connection, s: Store, card: dict[str, Any]) -> None:
    s.put("recommendation", {**card, "status": "superseded"})
    publish(conn, new_event("recommendation.status_changed", card["company_id"],
                            {"recommendation_id": card["id"], "status": "superseded"}, producer="agents"))


def reset(conn: psycopg.Connection, company: str) -> dict[str, Any]:
    s = Store(conn)
    open_cards = s.list("recommendation", company_id=company, status=["new", "seen"])
    chat = [c for c in open_cards if c["agent"] == "chat"
            or (c["type"] == "chase_receivable" and CHAT_REMINDER.match(c["id"]))]
    for card in chat:
        _supersede(conn, s, card)

    forecast = tools.latest_forecast(conn, company)
    stale_tax = ingestion.supersede_stale_tax_cards(conn, company, forecast) if forecast else []

    credit_line = next((c["id"] for c in open_cards if c["type"] == "credit_line"), None)
    if credit_line is None and forecast:
        facts = liquidity.facts_for(conn, company, forecast["id"])
        if facts:
            card = liquidity.template_recommendation(company, facts, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
            card["id"] = f"{card['id']}_{uuid.uuid4().hex[:6]}"
            if save_recommendation(conn, card):
                credit_line = card["id"]
    conn.commit()
    return {"company": company, "chat_cards_removed": [c["id"] for c in chat], "stale_tax_cards_removed": stale_tax,
            "open_credit_line": credit_line}


def run(argv: list[str]) -> int:
    companies = argv or ["co_borsuk"]
    with psycopg.connect(database_url(), autocommit=False) as conn:
        for company in companies:
            result = reset(conn, company)
            print(f"{company}: removed {len(result['chat_cards_removed'])} chat card(s), "
                  f"{len(result['stale_tax_cards_removed'])} stale tax card(s); "
                  f"open credit line: {result['open_credit_line'] or 'none (no cash gap in the forecast)'}")
    return 0
