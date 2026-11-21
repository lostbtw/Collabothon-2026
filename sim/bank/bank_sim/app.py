"""Sandbox Bank simulator: a PSD2-shaped account-information API plus three simulated execution targets."""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .csv_loader import PROFILES, CsvError, parse_commerzbank_csv
from .store import Account, Store, money

REF_RE = re.compile(r"^E\d{9}$")
DEFAULT_LIMIT = 500


class CreditLineIn(BaseModel):
    accountId: str
    limit: Decimal = Field(gt=0)
    tenorDays: int = Field(gt=0)


class FxForwardIn(BaseModel):
    accountId: str
    sellCurrency: str = Field(min_length=3, max_length=3)
    buyCurrency: str = Field(min_length=3, max_length=3)
    notional: Decimal = Field(gt=0)
    rate: Decimal = Field(gt=0)
    valueDate: date


class PaymentDraftIn(BaseModel):
    debtorAccount: str
    creditorName: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    remittance: str = ""
    requestedExecutionDate: date | None = None


class AdminTransactionIn(BaseModel):
    accountId: str
    amount: Decimal
    bookingDate: date | None = None
    valueDate: date | None = None
    currency: str | None = None
    creditorName: str | None = None
    debtorName: str | None = None
    remittance: str = ""
    cardLast4: str | None = Field(default=None, pattern=r"^\d{4}$")
    transactionCode: str | None = None


def autoload_plan(csv_path: str | None, csv_account: str, csv_dir: str | None) -> list[tuple[str, str]]:
    plan: list[tuple[str, str]] = []
    if csv_dir:
        folder = Path(csv_dir)
        if not folder.is_dir():
            raise RuntimeError(f"BANK_AUTOLOAD_DIR '{csv_dir}' is not a folder")
        plan += [(f"acc_{p.stem.removeprefix('bank_acc_')}", str(p)) for p in sorted(folder.glob("bank_acc_*.csv"))]
        if not plan:
            raise RuntimeError(f"BANK_AUTOLOAD_DIR '{csv_dir}' has no bank_acc_*.csv files")
    if csv_path:
        plan.append((csv_account, csv_path))
    return plan


def create_app(store: Store | None = None, token: str | None = None, autoload_csv: str | None = None,
               autoload_account: str | None = None, autoload_dir: str | None = None) -> FastAPI:
    store = store or Store()
    expected = token or os.environ.get("BANK_TOKEN", "demo-token")
    plan = autoload_plan(autoload_csv or os.environ.get("BANK_AUTOLOAD_CSV"),
                         autoload_account or os.environ.get("BANK_AUTOLOAD_ACCOUNT", "acc_pizzeria"),
                         autoload_dir or os.environ.get("BANK_AUTOLOAD_DIR"))
    app = FastAPI(title="Sandbox Bank simulator (SIMULATED)", version="0.1.0")
    app.state.store = store

    def apply_autoload() -> None:
        for account_id, path in plan:
            acc = store.accounts.get(account_id)
            if acc is None:
                raise RuntimeError(f"autoload: '{account_id}' (for {path}) is not a known account")
            try:
                with open(path, "rb") as f:
                    iban, lines = parse_commerzbank_csv(f.read())
            except (OSError, CsvError) as exc:  # fail fast: a bank that silently starts empty ruins the demo
                raise RuntimeError(f"autoload: '{path}' could not be loaded: {exc}") from exc
            acc.set_lines(lines)
            if iban:
                acc.iban = iban

    def bearer(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {expected}":
            raise HTTPException(401, "TOKEN_INVALID: missing or wrong bearer token")

    def consent(consent_id: str | None = Header(default=None, alias="Consent-ID")) -> None:
        if consent_id != "demo":
            raise HTTPException(403, "CONSENT_INVALID: header 'Consent-ID: demo' is required")

    psd2 = [Depends(bearer), Depends(consent)]
    admin = [Depends(bearer)]

    def account_or_404(account_id: str) -> Account:
        acc = store.accounts.get(account_id)
        if acc is None:
            raise HTTPException(404, f"RESOURCE_UNKNOWN: account {account_id}")
        return acc

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "simulated": True}

    @app.get("/v1/accounts", dependencies=psd2)
    def list_accounts() -> dict:
        return {"accounts": [a.to_resource() for a in store.accounts.values()]}

    @app.get("/v1/accounts/{account_id}/balances", dependencies=psd2)
    def balances(account_id: str) -> dict:
        acc = account_or_404(account_id)
        closing = store.closing_balance(acc)
        ref = store.reference_date(acc)
        out = []
        if closing is not None:
            out.append({
                "balanceType": "closingBooked",
                "balanceAmount": {"amount": money(closing), "currency": acc.currency},
                "referenceDate": ref.isoformat() if ref else None,
            })
        return {"account": {"iban": acc.iban}, "balances": out}

    @app.get("/v1/accounts/{account_id}/transactions", dependencies=psd2)
    def transactions(
        account_id: str,
        bookingStatus: str = "booked",
        dateFrom: date | None = None,
        entryReferenceFrom: str | None = None,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=1000),
    ) -> dict:
        acc = account_or_404(account_id)
        if bookingStatus not in ("booked", "both"):
            raise HTTPException(400, "FORMAT_ERROR: bookingStatus must be 'booked' (or 'both')")
        if entryReferenceFrom is not None and not REF_RE.match(entryReferenceFrom):
            raise HTTPException(400, "FORMAT_ERROR: entryReferenceFrom must look like E000000731")
        lines = list(acc.lines)
        if entryReferenceFrom:
            lines = [ln for ln in lines if ln.entry_reference > entryReferenceFrom]
        if dateFrom:
            lines = [ln for ln in lines if ln.booking_date >= dateFrom]
        page, more = lines[:limit], len(lines) > limit
        body: dict = {
            "account": {"iban": acc.iban},
            "transactions": {"booked": [ln.to_booked() for ln in page], "pending": []},
        }
        if more:
            href = (f"/v1/accounts/{account_id}/transactions?bookingStatus=booked"
                    f"&entryReferenceFrom={page[-1].entry_reference}&limit={limit}")
            if dateFrom:
                href += f"&dateFrom={dateFrom.isoformat()}"
            body["_links"] = {"next": {"href": href}}
        return body

    # Simulated execution targets: nothing here moves a balance.
    def record(kind: str, ref: str, payload: dict) -> None:
        store.executions.append({"type": kind, "reference": ref, "simulated": True, **payload})

    @app.post("/v1/credit-line-applications", status_code=201, dependencies=psd2)
    def credit_line(body: CreditLineIn) -> dict:
        acc = account_or_404(body.accountId)
        ref = store.new_reference("CL")
        available = store.today() + timedelta(days=1)
        out = {"reference": ref, "status": "accepted", "availableFrom": available.isoformat(),
               "accountId": acc.resource_id, "limit": money(body.limit), "tenorDays": body.tenorDays}
        record("credit_line_application", ref, out)
        return out

    @app.post("/v1/fx-forwards", status_code=201, dependencies=psd2)
    def fx_forward(body: FxForwardIn) -> dict:
        acc = account_or_404(body.accountId)
        if body.sellCurrency.upper() == body.buyCurrency.upper():
            raise HTTPException(400, "FORMAT_ERROR: sellCurrency and buyCurrency must differ")
        ref = store.new_reference("FX")
        out = {"reference": ref, "status": "booked", "accountId": acc.resource_id,
               "sellCurrency": body.sellCurrency.upper(), "buyCurrency": body.buyCurrency.upper(),
               "notional": money(body.notional), "rate": str(body.rate), "valueDate": body.valueDate.isoformat()}
        record("fx_forward", ref, out)
        return out

    @app.post("/v1/payment-drafts", status_code=201, dependencies=psd2)
    def payment_draft(body: PaymentDraftIn) -> dict:
        acc = account_or_404(body.debtorAccount)
        ref = store.new_reference("PD")
        when = body.requestedExecutionDate or store.today()
        out = {"reference": ref, "status": "draft", "debtorAccount": acc.resource_id,
               "creditorName": body.creditorName, "amount": money(body.amount), "currency": acc.currency,
               "remittance": body.remittance, "requestedExecutionDate": when.isoformat()}
        record("payment_draft", ref, out)
        return out

    @app.post("/admin/transactions", status_code=201, dependencies=admin)
    def admin_transaction(body: AdminTransactionIn) -> dict:
        acc = account_or_404(body.accountId)
        if body.amount == 0:
            raise HTTPException(400, "FORMAT_ERROR: amount must not be zero")
        booking = body.bookingDate or store.today()
        name = body.creditorName if body.amount < 0 else body.debtorName
        name = name or body.creditorName or body.debtorName
        code = body.transactionCode or ("CARD_PAYMENT" if body.cardLast4 else "TRANSFER")
        line = store.add_line(
            acc, booking_date=booking, value_date=body.valueDate or booking, amount=body.amount,
            currency=(body.currency or acc.currency).upper(), counterparty_name=name, counterparty_iban=None,
            remittance=body.remittance, code=code, card_last4=body.cardLast4,
        )
        return line.to_booked()

    @app.post("/admin/load-csv", dependencies=admin)
    async def load_csv(request: Request, profile: str = "commerzbank_csv", accountId: str = "acc_pizzeria") -> dict:
        if profile not in PROFILES:
            raise HTTPException(400, f"unknown profile '{profile}', supported: {sorted(PROFILES)}")
        acc = account_or_404(accountId)
        try:
            iban, lines = parse_commerzbank_csv(await request.body())
        except CsvError as exc:
            raise HTTPException(422, f"CSV_INVALID: {exc}") from exc
        acc.set_lines(lines)
        if iban:
            acc.iban = iban
        return {"accountId": acc.resource_id, "lines": len(lines),
                "firstBookingDate": lines[0].booking_date.isoformat(),
                "lastBookingDate": lines[-1].booking_date.isoformat(),
                "lastEntryReference": lines[-1].entry_reference}

    @app.get("/admin/executions", dependencies=admin)
    def executions() -> dict:
        return {"executions": store.executions}

    @app.post("/admin/reset", dependencies=admin)
    def reset() -> dict:
        store.reset()
        apply_autoload()
        return {"status": "reset", "autoloaded": bool(plan)}

    apply_autoload()
    return app


app = create_app()
