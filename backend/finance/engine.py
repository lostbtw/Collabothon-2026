"""The finance engine's database side (#28): `recompute(conn, company_id) -> Forecast`.

Role 5 calls it through backend/api/ports.py (`finance_engine().recompute`) after owner events and executed
actions; the finance consumer calls it after new bank lines and approved Ledger entries (backend/finance/main.py).

    1. read the company's data up to its as-of date (D-21)
    2. build the forecast with the pure function backend/finance/forecast.py
    3. write `recurring_series_id` onto the bank lines of detected series (role 3 auto-confirms only those)
    4. store the forecast and emit `forecast.updated`; unchanged inputs (same `inputs_hash`) do nothing
"""
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store

from .forecast import HORIZON_DAYS, build_forecast, recurring_series_ids, summarise
from .series import name_key

log = logging.getLogger("ordo.finance")
PRODUCER = "finance"

# Demo-day rates, used everywhere (spec #4); NBP rates replace them when role 2's rate connector lands.
DEMO_DAY_RATES_PLN = {"PLN": Decimal("1"), "EUR": Decimal("4.41"), "USD": Decimal("4.0613")}
# Spec #4: the pizzeria's forecast is seen from 15 May 2025; its July gap (3 Jul) is 49 days ahead.
HORIZON_BY_COMPANY = {"co_amalfi": 60}
# Safety buffer per company (contracts/fixtures/forecast.json); below it the forecast raises `below_buffer`.
SAFETY_BUFFER = {"co_borsuk": Decimal("10000")}
SETTLED = {"confirmed", "auto_confirmed"}
DEFAULT_PAYMENT_DAYS = 14


def rates_for(base: str) -> dict[str, Decimal]:
    """Base-currency units per 1 unit of each currency."""
    if base not in DEMO_DAY_RATES_PLN:
        return {base: Decimal(1)}
    return {c: r / DEMO_DAY_RATES_PLN[base] for c, r in DEMO_DAY_RATES_PLN.items()}


def _company(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    row = conn.execute("select id, name, base_currency, country, as_of_date from companies where id = %s",
                       (company_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown company {company_id}")
    id_, name, base, country, as_of = row
    return {"id": id_, "name": name, "base_currency": base, "country": country, "as_of_date": str(as_of)}


def _accounts(accounts: list[dict], transactions: list[dict]) -> list[dict]:
    """Accounts with `opening_balance` = the balance before the first bank line we hold.

    The bank reports `balance` at `balance_at`; going back from it over the lines up to that moment is exact even
    when the stored `opening_balance` refers to another set of lines.
    """
    out = []
    for acc in accounts:
        bal = acc.get("balance")
        if bal and acc.get("balance_at"):
            until = acc["balance_at"][:10]
            booked = sum((Decimal(t["amount_base"]["amount"]) for t in transactions
                          if t.get("account_id") == acc["id"] and t["booking_date"] <= until), Decimal(0))
            acc = {**acc, "opening_balance": {"amount": f"{Decimal(bal['amount']) - booked:.2f}",
                                              "currency": bal["currency"]}}
        out.append(acc)
    return out


def _party(doc: dict) -> dict:
    return (doc.get("buyer") if doc.get("direction") == "sale" else doc.get("seller")) or {}


def _keys(party: dict) -> list[str]:
    return [k for k in (party.get("counterparty_id"), name_key(party.get("name"))) if k]


def _open_items(s: Store, company: dict, as_of: str) -> tuple[list[dict], set[str]]:
    """Open invoices known on the as-of date, and the keys of every client paid by invoice."""
    documents = [d for d in s.list("document", company_id=company["id"]) if d.get("status") not in ("duplicate", "rejected")]
    matches = s.list("match", company_id=company["id"])
    settled = {m["document_id"]: m for m in matches if m.get("status") in SETTLED and m.get("transaction_id")}
    private = {m["document_id"] for m in matches if m.get("paid_by") in ("employee_private", "owner_private")}
    counterparties = {c["id"]: c for c in s.list("counterparty", company_id=company["id"])}

    delays: dict[str, list[int]] = {}
    for doc in documents:  # how late each client paid before: payment booking date - due date
        m = settled.get(doc["id"])
        if doc.get("direction") == "sale" and m and doc.get("due_date"):
            txn = s.get("transaction", m["transaction_id"])
            if txn and txn["booking_date"] <= as_of:
                late = (date.fromisoformat(txn["booking_date"]) - date.fromisoformat(doc["due_date"])).days
                for k in _keys(_party(doc)):
                    delays.setdefault(k, []).append(max(late, 0))

    items, invoice_keys = [], set()
    for doc in documents:
        party = _party(doc)
        keys = _keys(party)
        if doc.get("direction") == "sale":
            invoice_keys.update(keys)
        issued = doc.get("issue_date") or doc.get("sale_date")
        if not issued or issued > as_of or doc["id"] in settled or not keys:
            continue
        payment = doc.get("payment") or {}
        if doc.get("direction") == "purchase" and (payment.get("paid") or doc["id"] in private
                                                   or payment.get("method") in ("card", "cash")):
            continue  # already paid, or owed to a person (that debt is in the Ledger)
        if doc.get("direction") not in ("sale", "purchase"):
            continue
        due = doc.get("due_date") or (date.fromisoformat(issued) + timedelta(days=DEFAULT_PAYMENT_DAYS)).isoformat()
        delay = 0
        if doc["direction"] == "sale":
            seen = next((delays[k] for k in keys if k in delays), None)
            cp = counterparties.get(party.get("counterparty_id") or "") or {}
            delay = round(sum(seen) / len(seen)) if seen else int(cp.get("typical_payment_delay_days") or 0)
        number = doc.get("number") or doc["id"]
        items.append({"id": doc["id"], "kind": "receivable" if doc["direction"] == "sale" else "payable",
                      "label": f"Invoice {number} {party.get('name') or ''}".strip(), "key": keys[0], "keys": keys,
                      "amount": doc["totals"]["gross"], "due_date": due, "delay_days": delay,
                      "confidence": 0.9 if delay <= 3 else 0.6})
    return items, invoice_keys


def load_inputs(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """Everything the pure forecast needs, read from the database."""
    s = Store(conn)
    company = _company(conn, company_id)
    as_of = company["as_of_date"]
    transactions = s.list("transaction", company_id=company_id)
    accounts = _accounts(s.list("account", company_id=company_id), transactions)
    open_items, invoice_keys = _open_items(s, company, as_of)
    people = conn.execute("select name from people where company_id = %s", (company_id,)).fetchall()
    people_keys = {name_key(n) for (n,) in people}
    people_keys |= {c["id"] for c in s.list("counterparty", company_id=company_id) if c.get("person_id")}
    ledger = [e for e in s.list("ledger_entry", company_id=company_id, type="reimbursement_liability",
                                status="approved") if not e.get("cash_date") or e["cash_date"] > as_of]
    events = [r[0] for r in conn.execute("select doc from forecast_events where company_id = %s order by seq",
                                         (company_id,)).fetchall()]
    return {"company": {k: company[k] for k in ("id", "base_currency", "as_of_date", "country")},
            "accounts": accounts, "transactions": transactions, "rates": rates_for(company["base_currency"]),
            "open_items": open_items, "ledger_entries": ledger, "events": events,
            "invoice_keys": sorted(invoice_keys), "people_keys": sorted(people_keys),
            "own_keys": [name_key(company["name"])],
            "horizon_days": HORIZON_BY_COMPANY.get(company_id, HORIZON_DAYS),
            "safety_buffer": SAFETY_BUFFER.get(company_id)}


def latest_base(conn: psycopg.Connection, company_id: str) -> dict[str, Any] | None:
    """The newest stored base forecast, by insertion order (a fixture's `generated_at` can lie in the future)."""
    row = conn.execute("select doc from forecasts where company_id = %s and scenario_of is null "
                       "order by seq desc limit 1", (company_id,)).fetchone()
    return row[0] if row else None


def latest(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """GET /forecast/latest: the engine's current forecast (the stored one when nothing changed, so no new event).

    Never a stale stand-in: a fixture forecast loaded for the demo is replaced by the first recompute.
    """
    return recompute(conn, company_id)


def ledger_kpis(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """KPIs of GET /ledger/summary (openapi: reimbursements_owed, vat_lost_ytd, documents_missing, tax_due_next_30d).

    vat_lost_ytd        non-deductible VAT on Ledger entries dated in the as-of date's year (VAT lost this year)
    reimbursements_owed debts to the team (reimbursement_liability) minus what was paid out (reimbursement_payout)
    documents_missing   bank lines that wait for a document
    tax_due_next_30d    tax and social-security payments in the forecast within 30 days after the as-of date
    """
    s = Store(conn)
    company = _company(conn, company_id)
    base, as_of = company["base_currency"], date.fromisoformat(company["as_of_date"])
    entries = [e for e in s.list("ledger_entry", company_id=company_id) if e.get("status") != "void"]

    def total(values) -> Decimal:
        return sum((Decimal(v) for v in values), Decimal(0))

    vat_lost = total(e["vat"]["amount"]["amount"] for e in entries
                     if e.get("vat") and e["vat"].get("deductible") is False and str(e.get("date", ""))[:4] == str(as_of.year))
    owed = total(e["amount_base"]["amount"] for e in entries if e["type"] == "reimbursement_liability")
    paid = total(e["amount_base"]["amount"] for e in entries if e["type"] == "reimbursement_payout")
    missing = len(s.list("transaction", company_id=company_id, match_status="missing_document"))
    forecast = latest(conn, company_id)
    until = (as_of + timedelta(days=30)).isoformat()
    tax = Decimal(0)
    for c in forecast["components"]:
        if c["kind"] in ("tax", "social_security") and c["dates"]:
            each = Decimal(c["amount_base"]["amount"]) / len(c["dates"])
            tax += each * sum(1 for d in c["dates"] if as_of.isoformat() < d <= until)

    def m(value: Decimal) -> dict[str, str]:
        return {"amount": f"{value.quantize(Decimal('0.01')):.2f}", "currency": base}

    return {"reimbursements_owed": m(abs(owed) - abs(paid)), "vat_lost_ytd": m(vat_lost),
            "documents_missing": missing, "tax_due_next_30d": m(abs(tax))}


def _write_series_ids(s: Store, transactions: list[dict], ids: dict[str, str], company_id: str) -> int:
    changed = 0
    for t in transactions:
        new = ids.get(t["id"])
        if t.get("recurring_series_id") != new:
            s.put("transaction", {**t, "recurring_series_id": new}, company_id=company_id)
            changed += 1
    return changed


def recompute(conn: psycopg.Connection, company_id: str, *, correlation_id: str | None = None,
              causation_id: str | None = None) -> dict[str, Any]:
    """The company's current base forecast: a new one when its inputs changed, else the stored one."""
    s = Store(conn)
    inputs = load_inputs(conn, company_id)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    forecast = build_forecast(**inputs, generated_at=now)
    stored = conn.execute("select doc from forecasts where company_id = %s and inputs_hash = %s",
                          (company_id, forecast["inputs_hash"])).fetchone()
    if stored:
        return stored[0]  # same inputs: same numbers, no event

    ids = recurring_series_ids(**{k: inputs[k] for k in ("company", "accounts", "transactions", "rates", "own_keys")})
    changed = _write_series_ids(s, inputs["transactions"], ids, company_id)
    previous = latest_base(conn, company_id)
    s.add("forecast", forecast, company_id=company_id)
    publish(conn, new_event("forecast.updated", company_id, {
        "forecast_id": forecast["id"],
        "min_balance": forecast["min_balance"]["amount"],
        "min_balance_previous": previous["min_balance"]["amount"] if previous else None,
        "first_negative_date": forecast["first_negative_date"],
    }, producer=PRODUCER, correlation_id=correlation_id, causation_id=causation_id))
    log.info("finance: %s forecast %s, low %s on %s (%d series ids written)", company_id, forecast["id"],
             forecast["min_balance"]["amount"]["amount"], forecast["min_balance"]["date"], changed)
    return forecast


def scenario(conn: psycopg.Connection, company_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """What-if on the latest stored base forecast, stored with `scenario_of` (POST /forecast/scenario).

    `credit_line` {limit: Money, from}: the limit is available from that date (default: the as-of date), so every
    balance from then on is higher by it. Shifted receivables and payables arrive with #44 (4.3); until then such
    a request is listed as an assumption and changes no number.
    """
    base = latest_base(conn, company_id) or recompute(conn, company_id)
    currency = base["base_currency"]
    points = [dict(p) for p in base["points"]]
    components = list(base["components"])
    assumptions = list(base["assumptions"])
    line = body.get("credit_line")
    if line:
        limit = Decimal(line["limit"]["amount"])
        start = line.get("from") or base["as_of_date"]
        for p in points:
            if p["date"] >= start:
                for k in ("balance", "low", "high"):
                    if p.get(k) is not None:
                        p[k] = f"{Decimal(p[k]) + limit:.2f}"
        components.append({"id": "c_credit_line", "label": f"Credit line {limit:,.2f} {currency} (simulated)",
                           "kind": "scenario_action", "amount_base": {"amount": f"{limit:.2f}", "currency": currency},
                           "schedule": f"available from {start}", "dates": [start], "confidence": 1.0,
                           "evidence": [{"kind": "forecast", "id": base["id"], "label": "Base forecast",
                                         "url": f"/forecast/{base['id']}"}]})
    for other in sorted(k for k in body if k != "credit_line"):
        assumptions.append(f"Scenario '{other}' requested; it is computed with #44, not yet")
    as_of = date.fromisoformat(base["as_of_date"])
    buffer = Decimal(base["safety_buffer"]["amount"]) if base.get("safety_buffer") else None
    min_balance, first_negative, alerts = summarise(points, as_of, currency, buffer)
    now = datetime.now(UTC)
    copy = {**base, "id": f"{base['id']}_s{now:%H%M%S%f}", "scenario_of": base["id"], "inputs_hash": None,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "points": points, "components": components,
            "assumptions": assumptions, "min_balance": min_balance, "first_negative_date": first_negative,
            "alerts": alerts}
    Store(conn).add("forecast", copy, company_id=company_id)
    return copy
