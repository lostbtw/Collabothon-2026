"""The finance engine's database side (#28): `recompute(conn, company_id) -> Forecast`.

Role 5 calls it through backend/api/ports.py (`finance_engine().recompute`) after owner events and executed
actions; the finance consumer calls it after new bank lines and approved Ledger entries (backend/finance/main.py).

    1. read the company's data up to its as-of date (D-21)
    2. build the forecast with the pure function backend/finance/forecast.py
    3. write `recurring_series_id` onto the bank lines of detected series (role 3 auto-confirms only those)
    4. store the forecast and emit `forecast.updated`; unchanged inputs (same `inputs_hash`) do nothing
"""
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store

from . import fx
from .forecast import build_forecast, recurring_series_ids
from .scenarios import credit_line_size, stress_of, with_changes
from .series import name_key
from .settings import (BUFFER_MONTHS, BUFFER_ROUND, BUFFER_SHARE, DEFAULT_PAYMENT_DAYS, DEMO_DAY_RATES_PLN,
                       EVENT_TAIL_DAYS, FX_HISTORY_DAYS, FX_MIN_HISTORY, HORIZON_DAYS)
from .tax import tax_document

try:  # role 2's NBP connector (#34): stored table A rates
    from backend.connectors.nbp import rate_on
except ImportError:  # pragma: no cover
    rate_on = None

try:  # role 2's stored NBP tables (#34); FX Shield falls back to the committed 3-year file without them
    from backend.connectors.nbp import history as nbp_history
except ImportError:  # pragma: no cover
    nbp_history = None

DATA = Path(__file__).resolve().parent / "data"
FX_HISTORY_FILE = DATA / "nbp_history_3y.json"

log = logging.getLogger("ordo.finance")
PRODUCER = "finance"

SETTLED = {"confirmed", "auto_confirmed"}


def _pln_per_unit(conn: psycopg.Connection | None, currency: str, on: date) -> tuple[Decimal, str] | None:
    """PLN for 1 unit: the stored NBP table A rate of `on` (or the last one before), else the demo-day rate."""
    if currency == "PLN":
        return Decimal(1), "PLN"
    found = rate_on(conn, currency, on, "booking_day") if (conn is not None and rate_on) else None
    if found:
        return Decimal(found["rate"]), f"{found['source']} of {found['rate_date']}"
    if currency in DEMO_DAY_RATES_PLN:
        return DEMO_DAY_RATES_PLN[currency], "demo-day rate (spec #4)"
    return None


def rates_for(base: str, currencies: set[str], on: date, conn: psycopg.Connection | None = None) -> dict[str, Decimal]:
    """Base-currency units per 1 unit of each currency the company holds or invoices in."""
    rates = {base: Decimal(1)}
    base_pln = _pln_per_unit(conn, base, on)
    for currency in sorted(currencies - {base}):
        pln = _pln_per_unit(conn, currency, on)
        if pln and base_pln:
            rates[currency] = pln[0] / base_pln[0]
    return rates


def horizon_for(as_of: str, events: list[dict]) -> int:
    """The default horizon, longer when an owner event ends late: the event and what follows it stay visible."""
    last_end = max((e["date_to"] for e in events), default=None)
    if last_end is None:
        return HORIZON_DAYS
    needed = (date.fromisoformat(last_end) - date.fromisoformat(as_of)).days + EVENT_TAIL_DAYS
    return max(HORIZON_DAYS, needed)


def safety_buffer_for(transactions: list[dict], accounts: list[dict], rates: dict[str, Decimal],
                      as_of: str) -> Decimal | None:
    """A share of the average monthly outflows of the last full months before the as-of date, rounded up."""
    liquid = {a["id"] for a in accounts if a.get("include_in_liquidity")}
    first = date.fromisoformat(as_of).replace(day=1)
    months = []
    for _ in range(BUFFER_MONTHS):
        first = (first - timedelta(days=1)).replace(day=1)
        months.append(first.isoformat()[:7])
    out = Decimal(0)
    for t in transactions:
        amount = Decimal(t["amount_base"]["amount"])
        if t.get("account_id") in liquid and amount < 0 and t["booking_date"][:7] in months:
            out += -amount * rates.get(t["amount_base"]["currency"], Decimal(1))
    if out == 0:
        return None
    raw = out / len(months) * BUFFER_SHARE
    return (raw / BUFFER_ROUND).to_integral_value(rounding="ROUND_CEILING") * BUFFER_ROUND


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
    # For cash, a document matched to a bank line is paid: the money already moved, confirmed by the owner or not.
    # Waiting for it again would count it twice (with role 3's `suggested` matches, every sales invoice of the year
    # looked open). Only a match the owner rejected leaves the document open.
    settled = {m["document_id"]: m for m in matches if m.get("transaction_id") and m.get("status") != "rejected"}
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


def fx_locks(s: Store, company_id: str) -> dict[str, dict[str, str]]:
    """{document id: {rate, ratio, reference}} of every FX forward the owner approved and the Sandbox Bank booked
    (an executed fx_hedge card, #47): that share of the invoice no longer moves with the rate."""
    locks = {}
    for r in s.list("recommendation", company_id=company_id, agent="fx", status="executed_simulated"):
        subject = (r.get("subject") or {}).get("id")
        action = r.get("proposed_action") or {}
        if r.get("type") != "fx_hedge" or not subject or action.get("kind") != "book_fx_forward":
            continue
        params = dict(action.get("params") or {})
        approval = s.get("approval", r["approval_id"]) if r.get("approval_id") else None
        for path, value in ((approval or {}).get("changes") or {}).items():  # the owner may have edited the action
            if path.startswith("proposed_action.params."):
                params[path.removeprefix("proposed_action.params.")] = value
        reference = ((approval or {}).get("execution") or {}).get("reference") or r["id"]
        locks[subject] = {"rate": str(params["rate"]), "ratio": str(params.get("hedge_ratio", 1)), "reference": reference}
    return locks


def load_inputs(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """Everything the pure forecast needs, read from the database."""
    s = Store(conn)
    company = _company(conn, company_id)
    as_of = company["as_of_date"]
    transactions = s.list("transaction", company_id=company_id)
    accounts = _accounts(s.list("account", company_id=company_id), transactions)
    open_items, invoice_keys = _open_items(s, company, as_of)
    locks = fx_locks(s, company_id)
    open_items = [{**i, "locked": locks[i["id"]]} if i["id"] in locks else i for i in open_items]
    people = conn.execute("select name from people where company_id = %s", (company_id,)).fetchall()
    people_keys = {name_key(n) for (n,) in people}
    people_keys |= {c["id"] for c in s.list("counterparty", company_id=company_id) if c.get("person_id")}
    ledger = [e for e in s.list("ledger_entry", company_id=company_id, type="reimbursement_liability",
                                status="approved") if not e.get("cash_date") or e["cash_date"] > as_of]
    documents = s.list("document", company_id=company_id)
    events = [r[0] for r in conn.execute("select doc from forecast_events where company_id = %s order by seq",
                                         (company_id,)).fetchall()]
    currencies = {a["currency"] for a in accounts} | {i["amount"]["currency"] for i in open_items}
    rates = rates_for(company["base_currency"], currencies, date.fromisoformat(as_of), conn)
    return {"company": {k: company[k] for k in ("id", "base_currency", "as_of_date", "country")},
            "accounts": accounts, "transactions": transactions, "rates": rates,
            "open_items": open_items, "ledger_entries": ledger, "events": events,
            "tax_documents": [t for t in map(tax_document, documents) if t],
            "invoice_keys": sorted(invoice_keys), "people_keys": sorted(people_keys),
            "own_keys": [name_key(company["name"])],
            "horizon_days": horizon_for(as_of, events),
            "safety_buffer": safety_buffer_for(transactions, accounts, rates, as_of)}


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

    vat_lost_ytd        non-deductible VAT on approved Ledger entries dated in the as-of date's year (VAT lost this year)
    reimbursements_owed approved debts to the team (reimbursement_liability) minus what was paid out (reimbursement_payout)
    documents_missing   bank lines that wait for a document
    tax_due_next_30d    tax and social-security payments in the forecast within 30 days after the as-of date
    """
    s = Store(conn)
    company = _company(conn, company_id)
    base, as_of = company["base_currency"], date.fromisoformat(company["as_of_date"])
    entries = [e for e in s.list("ledger_entry", company_id=company_id) if e.get("status") == "approved"]

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
    """POST /forecast/scenario: the latest stored base forecast with the request applied, stored with `scenario_of`.

    credit_line {limit, from}, shift_receivable {document_id, new_date}, shift_payable {component_id, days}
    (backend/finance/scenarios.py). A scenario is never the base forecast.
    """
    base = latest_base(conn, company_id) or recompute(conn, company_id)
    result = with_changes(base, body)
    now = datetime.now(UTC)
    result.update(id=f"{base['id']}_s{now:%H%M%S%f}", scenario_of=base["id"], inputs_hash=None,
                  generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    Store(conn).add("forecast", result, company_id=company_id)
    return result


def stress(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """The stress case of the latest base forecast: {label, date, balance, receivable_component_id, extra_days}."""
    return stress_of(latest_base(conn, company_id) or recompute(conn, company_id))


def credit_line(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """The credit line that covers the worst case: {limit, shortfall, basis, rule, stress}."""
    return credit_line_size(latest_base(conn, company_id) or recompute(conn, company_id))


# ---------- FX Shield (#47) ----------
def fx_history_pln(conn: psycopg.Connection | None, currency: str, as_of: date) -> dict[str, str]:
    """{day: PLN per unit}: the NBP tables the connector stored, or the committed 3-year file when fewer than
    FX_MIN_HISTORY of them fall in the 3 years before the as-of date."""
    stored: dict[str, str] = {}
    if conn is not None and nbp_history is not None:
        stored = dict(nbp_history(conn, currency, as_of - timedelta(days=FX_HISTORY_DAYS + 1)))
    if len(fx.history_window(stored, as_of)) >= FX_MIN_HISTORY:
        return stored
    return json.loads(FX_HISTORY_FILE.read_text(encoding="utf-8")).get(currency.upper(), {})


def fx_history(conn: psycopg.Connection | None, currency: str, base: str, as_of: date) -> dict[str, str]:
    """{day: base-currency units per unit}. NBP quotes PLN per unit; another base divides by its own PLN rate."""
    if base == "PLN":
        return fx_history_pln(conn, currency, as_of)
    base_pln = fx_history_pln(conn, base, as_of)
    pln = {d: "1" for d in base_pln} if currency == "PLN" else fx_history_pln(conn, currency, as_of)
    return {d: f"{Decimal(r) / Decimal(base_pln[d])}" for d, r in pln.items() if d in base_pln}


def fx_assessments(conn: psycopg.Connection, company_id: str) -> list[dict[str, Any]]:
    """FX Shield's numbers for every open foreign-currency invoice of the company (fx.assess_company)."""
    inputs = load_inputs(conn, company_id)
    company = inputs["company"]
    base, as_of = company["base_currency"], date.fromisoformat(company["as_of_date"])
    currencies = {i["amount"]["currency"] for i in inputs["open_items"]} - {base}
    histories = {c: fx_history(conn, c, base, as_of) for c in currencies}
    return fx.assess_company(inputs, histories, build_forecast(**inputs))


EXPOSURE_FIELDS = ("document_id", "direction", "amount", "value_today_base", "expected_cash_date", "horizon_days",
                   "scenarios", "bad_case_p95", "expected_shortfall", "verdict")


def fx_exposure(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    """GET /fx/exposure (contracts/openapi.yaml): one item per open foreign-currency invoice. The verdict is what FX
    Shield decided (its card): a hedge (`hedged` once approved), no hedge, or already covered; no verdict yet when
    the invoice has not been judged."""
    cards: dict[str, dict[str, Any]] = {}
    mine = Store(conn).list("recommendation", company_id=company_id, agent="fx")
    for r in sorted(mine, key=lambda r: r["created_at"]):  # the newest card of an invoice wins
        subject = (r.get("subject") or {}).get("id")
        if subject and r["status"] in ("new", "seen", "approved", "executed_simulated", "expired"):
            cards[subject] = r
    items = []
    for a in fx_assessments(conn, company_id):
        item = {k: a[k] for k in EXPOSURE_FIELDS if a.get(k) is not None}
        card = cards.get(a["document_id"])
        if a["status"] in ("naturally_hedged", "hedged"):
            item["verdict"] = a["status"]
        elif card and card["type"] == "fx_hedge":
            item["verdict"] = "hedged" if card["status"] in ("approved", "executed_simulated") else "hedge_proposed"
        elif card:
            item["verdict"] = "not_worth_it"
        shown = card if card and card["status"] != "expired" else None  # an ignored invoice has no card to open
        items.append({**item, "recommendation_id": shown["id"] if shown else None})
    return {"items": items}
