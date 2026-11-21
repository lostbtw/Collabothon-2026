"""In-memory state of the Sandbox Bank, rebuilt from the seed accounts and the CSVs on every start."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

# Booking rate only for the closing balance of the pizzeria's CHF lines in its EUR account (year-end 33,266.35 EUR).
BOOKING_RATES: dict[tuple[str, str], Decimal] = {("CHF", "EUR"): Decimal("1.043583")}


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


@dataclass
class Line:
    entry_reference: str
    booking_date: date
    value_date: date
    amount: Decimal
    currency: str
    counterparty_name: str | None
    counterparty_iban: str | None
    remittance: str
    code: str
    card_last4: str | None = None

    def to_booked(self) -> dict:
        out: dict = {
            "entryReference": self.entry_reference,
            "bookingDate": self.booking_date.isoformat(),
            "valueDate": self.value_date.isoformat(),
            "transactionAmount": {"amount": money(self.amount), "currency": self.currency},
            "remittanceInformationUnstructured": self.remittance,
            "proprietaryBankTransactionCode": self.code,
        }
        # Berlin Group naming: money out -> the counterparty is the creditor, money in -> the debtor
        party, account = ("creditorName", "creditorAccount") if self.amount < 0 else ("debtorName", "debtorAccount")
        if self.counterparty_name:
            out[party] = self.counterparty_name
        if self.counterparty_iban:
            out[account] = {"iban": self.counterparty_iban}
        if self.card_last4:
            out["cardLast4"] = self.card_last4
        return out


@dataclass
class Account:
    resource_id: str
    iban: str
    currency: str
    name: str
    owner_name: str
    cash_account_type: str = "CACC"
    opening_balance: Decimal | None = Decimal("0.00")  # None = no balance reported (private card)
    lines: list[Line] = field(default_factory=list)
    # Known balance after all loaded lines: the opening balance is derived from it, so the two never disagree.
    closing_target: Decimal | None = None

    def __post_init__(self) -> None:
        if self.closing_target is not None and not self.lines:
            self.opening_balance = self.closing_target

    def set_lines(self, lines: list[Line]) -> None:
        self.lines = lines
        if self.closing_target is not None:
            self.opening_balance = self.closing_target - sum(
                (in_currency(ln, self.currency) for ln in lines), Decimal(0))

    def next_reference(self) -> str:
        return f"E{len(self.lines) + 1:09d}"

    def to_resource(self) -> dict:
        return {
            "resourceId": self.resource_id, "iban": self.iban, "currency": self.currency,
            "name": self.name, "ownerName": self.owner_name, "cashAccountType": self.cash_account_type,
        }


def in_currency(line: Line, currency: str) -> Decimal:
    """A line's amount in the account currency (the pizzeria's CHF lines at the booking rate)."""
    if line.currency == currency:
        return line.amount
    return line.amount * BOOKING_RATES.get((line.currency, currency), Decimal(1))


def seed_accounts() -> dict[str, Account]:
    """Invented accounts; Borsuk Labs' IBANs and closing balances come from sim/scenario/world.py (check digits 00 on purpose)."""
    accounts = [
        Account("acc_pln", "PL00999900000000000000010001", "PLN", "Company account PLN (SAMPLE)",
                "BORSUK LABS SP Z O O (SAMPLE)", closing_target=Decimal("24730.15")),
        Account("acc_eur", "PL00999900000000000000010002", "EUR", "Company account EUR (SAMPLE)",
                "BORSUK LABS SP Z O O (SAMPLE)", closing_target=Decimal("3100.00")),
        Account("acc_owner", "PL00999900000000000000090021", "PLN", "Owner's private card (SAMPLE)",
                "Tomasz Borsuk (SAMPLE)", cash_account_type="CARD", opening_balance=None),
        Account("acc_pizzeria", "DE00 0000 0000 0000 0000 00", "EUR", "Pizzeria Amalfi business account (SAMPLE)",
                "Lucia Amalfi (SAMPLE)", opening_balance=Decimal("2500.00")),  # same as backend/db/seed_data/people.json
    ]
    return {a.resource_id: a for a in accounts}


class Store:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = seed_accounts()
        self.executions: list[dict] = []
        self._counters: dict[str, int] = {}

    def reset(self) -> None:
        self.__init__()

    def closing_balance(self, account: Account) -> Decimal | None:
        if account.opening_balance is None:
            return None
        total = account.opening_balance + sum(
            (in_currency(ln, account.currency) for ln in account.lines), Decimal(0))
        return total.quantize(CENT, rounding=ROUND_HALF_UP)

    def reference_date(self, account: Account) -> date | None:
        return max((ln.booking_date for ln in account.lines), default=None)

    def add_line(self, account: Account, **kw) -> Line:
        ln = Line(entry_reference=account.next_reference(), **kw)
        account.lines.append(ln)
        return ln

    def new_reference(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"SIM-{kind}-{self._counters[kind]:04d}"

    def today(self) -> date:
        return date.today()
