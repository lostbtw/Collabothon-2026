"""Simulated executor (#36, D-19). Owner: role 2.

Runs an approved action against the Sandbox Bank (contracts/bank-sim-api.md) and nothing else: never a real bank.

    result = execute_action(conn, approval, action, company)   # {"reference": "SIM-CL-0001", "result": "SIMULATED: ..."}

`action` is the Recommendation's `proposed_action` with the Approval's changes already applied (role 5 does that).
It also emits `execution.simulated`. The three bank actions go to the bank's targets; the actions the bank has no
target for are recorded as simulated drafts inside Ordo (no bank call, nothing sent):

| action kind              | where                                   | reference      |
|--------------------------|-----------------------------------------|----------------|
| apply_credit_line        | POST /v1/credit-line-applications       | SIM-CL-…       |
| create_payment_draft     | POST /v1/payment-drafts                 | SIM-PD-…       |
| schedule_transfer        | POST /v1/payment-drafts                 | SIM-PD-…       |
| move_to_tax_pocket       | POST /v1/payment-drafts (to the tax pocket) | SIM-PD-…   |
| book_fx_forward          | POST /v1/fx-forwards                    | SIM-FX-…       |
| send_email_draft         | Ordo only (draft, not sent)             | SIM-EM-YYYY-…  |
| book_ledger_entries      | Ordo only (role 4 books them)           | SIM-LE-YYYY-…  |

Environment: ORDO_BANK_URL, ORDO_BANK_TOKEN (shared with the bank connector).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import psycopg

from backend.connectors.bank import bank_token, make_client
from backend.db.events import new_event, publish

TAX_POCKET = "Tax pocket (SAMPLE)"


class ExecutionRefused(Exception):
    """The action must not run: not simulated, or not an action the executor knows."""


class ExecutionFailed(Exception):
    """The Sandbox Bank did not accept the action (unreachable, refused, invalid)."""


# ---------- helpers ----------
def _amount_text(amount: Any, currency: str | None) -> str:
    value = Decimal(str(amount))
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{text} {currency}" if currency else text


def _money(params: dict[str, Any], key: str) -> tuple[str, str | None]:
    m = params.get(key)
    if isinstance(m, dict):
        return str(m["amount"]), m.get("currency")
    if m is None:
        raise ExecutionRefused(f"the action has no {key!r}")
    return str(m), None


def _company_account(conn: psycopg.Connection, company: str, currency: str | None) -> str:
    """The company's own bank account to act on: one in `currency` if there is one, else its first account."""
    rows = conn.execute(
        """select id, doc->>'currency' from accounts where company_id = %s
           and coalesce(doc->>'kind', 'company_bank') = 'company_bank' order by id""", (company,)).fetchall()
    if not rows:
        raise ExecutionRefused(f"company {company} has no bank account to act on")
    for acc, cur in rows:
        if cur == currency:
            return acc
    return rows[0][0]


def _person_name(conn: psycopg.Connection, person_id: str | None) -> str | None:
    if not person_id:
        return None
    row = conn.execute("select name from people where id = %s", (person_id,)).fetchone()
    return row[0] if row else None


def _local_reference(conn: psycopg.Connection, prefix: str, decided_at: str | None) -> str:
    """A simulated reference for actions with no bank target (role 5's sequence, same format as its stand-in)."""
    seq = conn.execute("select nextval('sim_reference_seq')").fetchone()[0]
    year = (decided_at or datetime.now(UTC).isoformat())[:4]
    return f"SIM-{prefix}-{year}-{seq:04d}"


def _post(client: httpx.Client, token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = client.post(path, json=body, headers={"Authorization": f"Bearer {token}", "Consent-ID": "demo"})
    except httpx.HTTPError as exc:
        raise ExecutionFailed(f"Sandbox Bank unreachable: {exc}") from exc
    if resp.status_code >= 400:
        detail = resp.text[:200]
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise ExecutionFailed(f"Sandbox Bank refused the action (HTTP {resp.status_code}): {detail}")
    return resp.json()


# ---------- the actions ----------
def _credit_line(conn, client, token, company, p) -> tuple[str, str]:
    amount, currency = _money(p, "limit")
    account = p.get("account_id") or _company_account(conn, company, currency)
    tenor = int(p.get("tenor_days") or 90)
    out = _post(client, token, "/v1/credit-line-applications", {"accountId": account, "limit": amount, "tenorDays": tenor})
    return out["reference"], (f"Commerzbank accepted the credit-line application: limit {_amount_text(out['limit'], currency)}, "
                              f"{tenor} days, available from {out['availableFrom']}.")


def _payment_draft(conn, client, token, company, p, *, creditor: str | None = None) -> tuple[str, str]:
    amount, currency = _money(p, "amount")
    account = p.get("account_id") or _company_account(conn, company, currency)
    name = creditor or _person_name(conn, p.get("to")) or p.get("creditor_name") or p.get("to")
    if not name:
        raise ExecutionRefused("the payment has no recipient")
    body = {"debtorAccount": account, "creditorName": name, "amount": amount,
            "remittance": p.get("title") or p.get("remittance") or ""}
    if p.get("pay_on"):
        body["requestedExecutionDate"] = p["pay_on"]
    out = _post(client, token, "/v1/payment-drafts", body)
    when = f" for {out['requestedExecutionDate']}" if out.get("requestedExecutionDate") else ""
    return out["reference"], (f"Transfer draft of {_amount_text(out['amount'], out.get('currency') or currency)} "
                              f"to {name} added to the payment run{when} in the Sandbox Bank.")


def _fx_forward(conn, client, token, company, p) -> tuple[str, str]:
    notional, notional_ccy = _money(p, "notional")
    sell = (p.get("sell_currency") or notional_ccy or "").upper()
    buy = (p.get("buy_currency") or "").upper()
    if not sell or not buy or not p.get("rate") or not p.get("value_date"):
        raise ExecutionRefused("the forward needs sell_currency, buy_currency, notional, rate and value_date")
    account = p.get("account_id") or _company_account(conn, company, buy)
    out = _post(client, token, "/v1/fx-forwards", {"accountId": account, "sellCurrency": sell, "buyCurrency": buy,
                                                   "notional": notional, "rate": str(p["rate"]),
                                                   "valueDate": p["value_date"]})
    return out["reference"], (f"Forward booked at Commerzbank: sell {_amount_text(out['notional'], sell)} "
                              f"for {buy} at {out['rate']} on {out['valueDate']}.")


def _tax_pocket(conn, client, token, company, p) -> tuple[str, str]:
    return _payment_draft(conn, client, token, company, {"title": "Tax reserve", **p}, creditor=TAX_POCKET)


BANK_ACTIONS = {
    "apply_credit_line": _credit_line,
    "create_payment_draft": _payment_draft,
    "schedule_transfer": _payment_draft,
    "move_to_tax_pocket": _tax_pocket,
    "book_fx_forward": _fx_forward,
}


def execute_action(conn: psycopg.Connection, approval: dict[str, Any], action: dict[str, Any], company: str, *,
                   client: httpx.Client | None = None, token: str | None = None,
                   execution_mode: str = "simulated") -> dict[str, str]:
    """Run one approved action in simulation. Returns {"reference", "result"} and emits `execution.simulated`."""
    if execution_mode != "simulated":
        raise ExecutionRefused(f"execution mode {execution_mode!r} is refused: every action runs SIMULATED in this build")
    kind = (action or {}).get("kind")
    params = (action or {}).get("params") or {}
    token = token or bank_token()

    if kind in ("send_email_draft", "book_ledger_entries"):
        prefix, text = ("EM", "E-mail draft prepared in Ordo, not sent.") if kind == "send_email_draft" else \
                       ("LE", "Ledger entries marked for booking in Ordo.")
        reference = _local_reference(conn, prefix, approval.get("decided_at"))
    else:
        if kind not in BANK_ACTIONS:
            raise ExecutionRefused(f"no simulated target for action {kind!r}")
        if client is not None:
            reference, text = BANK_ACTIONS[kind](conn, client, token, company, params)
        else:
            with make_client() as own:
                reference, text = BANK_ACTIONS[kind](conn, own, token, company, params)

    result = "SIMULATED: " + text
    publish(conn, new_event("execution.simulated", company,
                            {"approval_id": approval["id"], "reference": reference, "result": result},
                            producer="executor"))
    return {"reference": reference, "result": result}
