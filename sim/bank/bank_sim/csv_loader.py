"""Loader for the organisers' bank statement (German online-banking CSV, ';' separated, newest first); CHF lines kept as-is."""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal

from .store import Line

PROFILES = {"commerzbank_csv"}
REQUIRED = {"Account Number", "Booking Date", "Value Date", "Transaction Type", "Payment Reference",
            "Beneficiary/Payer", "Counterparty Account", "Amount", "Currency"}


class CsvError(ValueError):
    pass


def _date(text: str) -> date:
    d, m, y = text.strip().split(".")
    year = int(y)
    return date(2000 + year if year < 100 else year, int(m), int(d))


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CsvError("file is not valid UTF-8 or Windows-1252 text")


def _code(transaction_type: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", transaction_type.upper()).strip("_")


def parse_commerzbank_csv(raw: bytes) -> tuple[str | None, list[Line]]:
    reader = csv.DictReader(io.StringIO(_decode(raw)), delimiter=";")
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise CsvError(f"missing columns: {', '.join(sorted(missing))}")
    parsed: list[tuple[date, int, dict]] = []
    for idx, row in enumerate(reader):
        try:
            booking = _date(row["Booking Date"])
            row["_amount"] = Decimal(row["Amount"].replace(".", "").replace(",", "."))
            row["_value"] = _date(row["Value Date"])
        except Exception as exc:  # noqa: BLE001
            raise CsvError(f"line {idx + 2}: {exc}") from exc
        parsed.append((booking, idx, row))
    if not parsed:
        raise CsvError("no data rows")
    parsed.sort(key=lambda t: (t[0], -t[1]))
    iban = parsed[0][2]["Account Number"].strip() or None
    lines = [
        Line(
            entry_reference=f"E{n:09d}", booking_date=booking, value_date=row["_value"],
            amount=row["_amount"], currency=row["Currency"].strip() or "EUR",
            counterparty_name=row["Beneficiary/Payer"].strip() or None,
            counterparty_iban=row["Counterparty Account"].strip() or None,
            remittance=row["Payment Reference"].strip(), code=_code(row["Transaction Type"]),
        )
        for n, (booking, _, row) in enumerate(parsed, start=1)
    ]
    return iban, lines
