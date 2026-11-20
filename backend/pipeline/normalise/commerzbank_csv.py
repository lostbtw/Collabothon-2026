"""STAND-IN for the Sandbox Bank's `POST /admin/load-csv?profile=commerzbank_csv` (role 2, ticket #13).

Reads the organisers' pizzeria statement (German online-banking CSV, newest line first) and returns
PSD2-shaped booked lines exactly as contracts/bank-sim-api.md describes them, wrapped in RawItems.
The CHF quirk is kept as-is: the normaliser must fix it. Remove this module once the bank connector (#22)
delivers real RawItems.

The CSV is event material and is git-ignored: keep it at materials/pizzeria-amalfi-bank-statement-2025-v6.csv.
"""
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from .money import german_decimal

DEFAULT_CSV = Path(__file__).resolve().parents[3] / "materials" / "pizzeria-amalfi-bank-statement-2025-v6.csv"


def _iso(day: str) -> str:
    return datetime.strptime(day, "%d.%m.%y").date().isoformat()


def read_booked_lines(path=DEFAULT_CSV) -> list[dict]:
    """CSV rows -> PSD2 booked lines, oldest first, with a strictly increasing entryReference."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";", quotechar='"'))
    rows.reverse()  # the file is newest first; the bank API pages oldest first
    rows.sort(key=lambda r: datetime.strptime(r["Booking Date"], "%d.%m.%y"))  # stable: keeps day order
    lines = []
    for n, r in enumerate(rows, start=1):
        amount = german_decimal(r["Amount"])
        party = r["Beneficiary/Payer"] or None
        account = r["Counterparty Account"] or None
        line = {
            "entryReference": f"E{n:09d}",
            "bookingDate": _iso(r["Booking Date"]),
            "valueDate": _iso(r["Value Date"]),
            "transactionAmount": {"amount": format(amount, "f"), "currency": r["Currency"]},
            "remittanceInformationUnstructured": r["Payment Reference"],
            "proprietaryBankTransactionCode": re.sub(r"[^A-Z0-9]+", "_", r["Transaction Type"].upper()).strip("_"),
        }
        if amount < 0:
            line["creditorName"] = party
            if account:
                line["creditorAccount"] = {"iban": account}
        else:
            line["debtorName"] = party
            if account:
                line["debtorAccount"] = {"iban": account}
        lines.append(line)
    return lines


def raw_items(lines: list[dict], source_id: str = "src_bank_pizzeria", account_key: str = "pizzeria",
              sync_run_id: str = "run_standin", fetched_at: str = "2025-12-31T23:59:59Z") -> list[dict]:
    """Wrap booked lines in RawItems as the bank connector (#22) will (raw_item.schema.json)."""
    items = []
    for line in lines:
        ref = line["entryReference"]
        items.append({
            "id": f"raw_{account_key}_{ref}",
            "source_id": source_id,
            "sync_run_id": sync_run_id,
            "kind": "bank_transaction",
            "external_id": ref,
            "idempotency_key": hashlib.sha256(f"bank_psd2:{account_key}:{ref}".encode()).hexdigest(),
            "parent_raw_item_id": None,
            "received_at": None,
            "fetched_at": fetched_at,
            "content_type": "application/json",
            "storage_uri": None,
            "sha256": None,
            "size_bytes": None,
            "metadata": {},
            "payload": line,
            "processing_status": "queued",
            "error": None,
        })
    return items
