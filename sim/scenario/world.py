"""Borsuk Labs (SAMPLE) world shared by the generators: company, accounts, people, demo-day rates."""
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

# Output folder; tests set SCENARIO_OUT to generate into a temporary folder.
OUT = Path(os.environ.get("SCENARIO_OUT") or Path(__file__).parent / "out")

COMPANY_ID = "co_borsuk"
COMPANY = "BORSUK LABS SP Z O O (SAMPLE)"
NIP = "9990000014"
AS_OF = date(2026, 11, 21)

# Demo-day rates, used everywhere.
RATES = {"PLN": Decimal("1"), "EUR": Decimal("4.41"), "USD": Decimal("4.0613")}

ACCOUNTS = {
    "acc_pln":   {"iban": "PL00999900000000000000010001", "currency": "PLN", "closing": Decimal("24730.15")},
    "acc_eur":   {"iban": "PL00999900000000000000010002", "currency": "EUR", "closing": Decimal("3100.00")},
    # Owner's private card *9021: read for company costs, never company cash.
    "acc_owner": {"iban": "PL00999900000000000000090021", "currency": "PLN", "opening": Decimal("12000.00")},
}

# Same ids, e-mails and fields as backend/db/seed_data/people.json, plus the rest of the team.
# 2 employees and 4 B2B contractors. "iban" stays in the scenario; it is not part of the People output.
PEOPLE = [
    {"id": "per_tomek", "company_id": COMPANY_ID, "name": "Tomasz Borsuk (SAMPLE)",
     "email": "owner@borsuk-labs.sample", "role": "owner", "iban": ACCOUNTS["acc_owner"]["iban"]},
    {"id": "per_jan", "company_id": COMPANY_ID, "name": "Jan Kowalski (SAMPLE)",
     "email": "jan@borsuk-labs.sample", "role": "employee", "iban": "PL00999900000000000000040001"},
    {"id": "per_marta", "company_id": COMPANY_ID, "name": "Marta Zielinska (SAMPLE)",
     "email": "marta@borsuk-labs.sample", "role": "employee", "iban": "PL00999900000000000000040002"},
    {"id": "per_anna", "company_id": COMPANY_ID, "name": "Anna Wrona (SAMPLE)",
     "email": "anna.wrona@devmail.sample", "role": "contractor", "iban": "PL00999900000000000000040003"},
    {"id": "per_piotr", "company_id": COMPANY_ID, "name": "Piotr Lis (SAMPLE)",
     "email": "piotr.lis@devmail.sample", "role": "contractor", "iban": "PL00999900000000000000040004"},
    {"id": "per_karolina", "company_id": COMPANY_ID, "name": "Karolina Mazur (SAMPLE)",
     "email": "karolina.mazur@devmail.sample", "role": "contractor", "iban": "PL00999900000000000000040005"},
    {"id": "per_michal", "company_id": COMPANY_ID, "name": "Michal Dudek (SAMPLE)",
     "email": "michal.dudek@devmail.sample", "role": "contractor", "iban": "PL00999900000000000000040006"},
    # Pizzeria owner exactly as in the seed (the pizzeria data itself comes from the organisers).
    {"id": "per_amalfi_owner", "company_id": "co_amalfi", "name": "Lucia Amalfi (SAMPLE)",
     "email": "owner@pizzeria-amalfi.sample", "role": "owner", "iban": None},
]
PERSON = {p["id"]: p for p in PEOPLE}


def bank_name(person_id):
    """Name as it appears in a bank line, e.g. 'JAN KOWALSKI (SAMPLE)'."""
    return PERSON[person_id]["name"].upper()
