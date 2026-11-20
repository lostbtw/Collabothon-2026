"""Forecast inputs from files already in the repo, read the way the app reads them (role 3's normaliser).

- Pizzeria Amalfi: the organisers' CSV (git-ignored event material; tests skip without it).
- Borsuk Labs: role 4's scenario (sim/scenario/out), same CSV format, plus its story items and People.
"""
import json
from decimal import Decimal
from pathlib import Path

from backend.finance.series import counterparty_key
from backend.pipeline.normalise.bank import normalise_bank_line
from backend.pipeline.normalise.commerzbank_csv import DEFAULT_CSV, raw_items, read_booked_lines

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "sim" / "scenario" / "out"
PIZZERIA_CSV = next((p for p in (DEFAULT_CSV, SCENARIO / DEFAULT_CSV.name) if p.is_file()), None)
RATES = {"PLN": "1", "EUR": "4.41", "USD": "4.0613"}  # demo-day rates (spec #4)
STORY_CLOSING = {"acc_pln": Decimal("24730.15"), "acc_eur": Decimal("3100.00")}  # 20 Nov 2026, sim/scenario/world.py


def bank_lines(path: Path, account: dict) -> list[dict]:
    return [normalise_bank_line(r, account) for r in raw_items(read_booked_lines(path), account_key=account["id"])]


def key(name: str) -> str:
    return counterparty_key({"counterparty_name_raw": name})


def pizzeria() -> dict:
    account = {"id": "acc_pizzeria", "currency": "EUR", "include_in_liquidity": True,
               "opening_balance": {"amount": "2500.00", "currency": "EUR"}}  # not in the file (spec #4)
    return {"company": {"id": "co_amalfi", "base_currency": "EUR", "as_of_date": "2025-05-15", "country": "DE"},
            "accounts": [account], "transactions": bank_lines(PIZZERIA_CSV, account), "rates": {"EUR": "1"}}


CLOSED_JUNE = {"id": "fev_june", "label": "Closed 1-30 June", "date_from": "2025-06-01", "date_to": "2025-06-30",
               "effect": "no_variable_flows", "amount": None, "source": "owner_form"}

CLIENTS = ["MEBLOSTYL SP Z O O (SAMPLE)", "PIEKARNIA ZLOTY KLOS SP Z O O (SAMPLE)", "KADROWNIA SP Z O O (SAMPLE)",
           "NORDWIND LOGISTIK GMBH (SAMPLE)"]


def borsuk(without: tuple[str, ...] = ()) -> dict:
    """Borsuk Labs on 21 Nov 2026: bank lines, open invoices of the story and the 10 approved reimbursements."""
    accounts = [{"id": "acc_pln", "currency": "PLN", "include_in_liquidity": True},
                {"id": "acc_eur", "currency": "EUR", "include_in_liquidity": True}]
    transactions = []
    for account in accounts:
        lines = bank_lines(SCENARIO / f"bank_{account['id']}.csv", account)
        # The story fixes the closing balance (sim/scenario/world.py); the opening one is derived from it, as the
        # scenario does, so regenerating the bank lines (e.g. other card rates) never moves the cash story.
        booked = sum((Decimal(t["amount_base"]["amount"]) for t in lines), Decimal(0))
        account["opening_balance"] = {"amount": f"{STORY_CLOSING[account['id']] - booked:.2f}",
                                      "currency": account["currency"]}
        transactions += lines
    people = json.loads((SCENARIO / "people.json").read_text(encoding="utf-8"))
    items = json.loads((SCENARIO / "story_items.json").read_text(encoding="utf-8"))
    open_items = [
        {"id": "doc_fv_2026_10_042", "kind": "receivable", "label": "Invoice 2026/10/042 Meblostyl",
         "key": key(CLIENTS[0]), "amount": {"amount": "36900.00", "currency": "PLN"}, "due_date": "2026-11-27",
         "delay_days": 0, "confidence": 0.9},
        {"id": "doc_fv_2026_10_044", "kind": "receivable", "label": "Invoice 2026/10/044 Nordwind Logistik",
         "key": key(CLIENTS[3]), "amount": {"amount": "18400.00", "currency": "EUR"}, "due_date": "2026-11-14",
         "delay_days": 23, "confidence": 0.6},
        {"id": "doc_fv_2026_11_045", "kind": "receivable", "label": "Invoice 2026/11/045 Lakeshore Robotics",
         "key": "lakeshore", "amount": {"amount": "40000.00", "currency": "USD"}, "due_date": "2027-01-05",
         "delay_days": 0, "confidence": 0.8},
    ]
    ledger = [{"id": f"led_{i['document_id']}", "type": "reimbursement_liability", "status": "approved",
               "cash_date": "2026-11-30", "amount_base": {"amount": i["amount_pln"], "currency": "PLN"},
               "explanation": i["description"]}
              for i in items if i["kind"] == "reimbursement" and i["document_id"] not in without]
    return {"company": {"id": "co_borsuk", "base_currency": "PLN", "as_of_date": "2026-11-21", "country": "PL"},
            "accounts": accounts, "transactions": transactions, "rates": RATES, "open_items": open_items,
            "ledger_entries": ledger, "invoice_keys": [key(c) for c in CLIENTS],
            "people_keys": [key(p["name"].upper()) for p in people],
            "own_ibans": ["PL00999900000000000000010001", "PL00999900000000000000010002"]}
