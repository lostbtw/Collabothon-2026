#!/usr/bin/env python3
"""Borsuk Labs (SAMPLE): People, story items after the as-of date, and the check that they reproduce the story table."""
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from bank_2026 import PAY_RUN_PLAN
from world import ACCOUNTS, AS_OF, COMPANY_ID, OUT, PEOPLE, PERSON, RATES

CENT = Decimal("0.01")

# The story rounds its EUR conversions, so values differ by up to ~45 PLN; if they differ, change the script, not the engine.
STORY = [
    (date(2026, 11, 21), "Opening: 24,730 PLN + 3,100 EUR", Decimal("38400")),
    (date(2026, 11, 25), "VAT for October", Decimal("24100")),
    (date(2026, 11, 27), "Meblostyl pays", Decimal("61000")),
    (date(2026, 11, 30), "Pay run + reimbursements", Decimal("-2169")),
    (date(2026, 12, 5), "Coworking, SaaS, card purchases (lowest)", Decimal("-7870")),
    (date(2026, 12, 7), "Nordwind pays 18,400 EUR", Decimal("73230")),
]
STRESS_LOW = Decimal("-28170")   # Nordwind pays 21 Dec instead of 7 Dec
LOW_BEFORE_LIVE_RECEIPT = Decimal("-6571")
TOLERANCE = Decimal("50")        # PLN, covers the story's rounding of EUR amounts


def m(amount, currency="PLN"):
    return {"amount": f"{Decimal(amount):.2f}", "currency": currency}


# Reimbursements owed on 30 Nov: 10 receipts paid with private cards = 5,169.00 PLN.
# M1: document in the person's own name / no company NIP; M2: document made out to the company.
# The live receipt (1,299 PLN, doc_rcpt412) arrives during the demo and moves the low from -6,571 to -7,870.
RECEIPTS = [
    ("doc_rcpt412", "per_jan", "2026-11-20", "ElektroMarkt Polska S.A. (SAMPLE)", "Monitor 27 cali QHD", "1299.00",
     "M1", False, True),
    ("doc_rcpt401", "per_marta", "2026-11-04", "Bistro Piotrkowska 90 s.c. (SAMPLE)", "Team lunch", "486.00",
     "M2", True, False),
    ("doc_rcpt402", "per_anna", "2026-11-05", "RailExpress S.A. (SAMPLE)", "Train ticket Lodz-Warszawa", "139.80",
     "M2", True, False),
    ("doc_rcpt403", "per_piotr", "2026-11-06", "DevCamp sp. z o.o. (SAMPLE)", "Workshop ticket", "1149.00",
     "M1", False, False),
    ("doc_rcpt404", "per_karolina", "2026-11-09", "Sklepik.pl sp. z o.o. (SAMPLE)", "Drawing tablet", "689.00",
     "M1", False, False),
    ("doc_rcpt405", "per_michal", "2026-11-10", "ElektroMarkt Polska S.A. (SAMPLE)", "USB-C hub", "219.00",
     "M1", False, False),
    ("doc_rcpt406", "per_jan", "2026-11-12", "Paliwex sp. z o.o. (SAMPLE)", "Fuel, client visit", "268.40",
     "M2", True, False),
    ("doc_rcpt407", "per_marta", "2026-11-13", "Biurosfera sp. z o.o. (SAMPLE)", "Office supplies", "154.30",
     "M2", True, False),
    ("doc_rcpt408", "per_anna", "2026-11-16", "Taxigo sp. z o.o. (SAMPLE)", "Taxi to client", "63.50",
     "M1", False, False),
    ("doc_rcpt409", "per_piotr", "2026-11-18", "Sushi Kamień sp. z o.o. (SAMPLE)", "Client dinner", "701.00",
     "M1", False, False),
]


def story_items():
    items = []

    def add(item_id, day, kind, description, counterparty, amount, currency="PLN", **extra):
        amount = Decimal(amount)
        items.append({
            "id": item_id, "date": day, "kind": kind, "description": description, "counterparty": counterparty,
            "amount": m(amount, currency),
            "amount_pln": f"{(amount * RATES[currency]).quantize(CENT, ROUND_HALF_UP):.2f}",
            **extra,
        })

    add("si_vat_10", "2026-11-25", "tax", "VAT-7 10/2026", "URZAD SKARBOWY LODZ-POLESIE", "-14300.00")
    add("si_meblostyl", "2026-11-27", "receivable", "FV 2026/10/042, due 27 Nov, client pays on time",
        "MEBLOSTYL SP Z O O (SAMPLE)", "36900.00", due_date="2026-11-27")
    for pid, ttype, ref, amount in PAY_RUN_PLAN:
        add(f"si_pay_{pid[4:]}", "2026-11-30", "payroll", f"{ttype.title()}: {ref.format(m=11, mm='11/2026')}",
            PERSON[pid]["name"], f"-{amount}", person_id=pid)
    for doc_id, pid, bought, seller, what, amount, case, company_nip, live in RECEIPTS:
        add(f"si_reimb_{doc_id[4:]}", "2026-11-30", "reimbursement", f"{what}, {seller}, bought {bought}",
            PERSON[pid]["name"], f"-{amount}", person_id=pid, document_id=doc_id, messiness=case,
            company_nip_on_document=company_nip, live_in_demo=live)
    add("si_coworking_12", "2026-12-01", "recurring", "CZYNSZ 12/2026 BIURO 4B",
        "COWORKING PIOTRKOWSKA SP Z O O (SAMPLE)", "-2460.00")
    add("si_bankfee_11", "2026-12-01", "recurring", "OPLATA ZA PROWADZENIE RACHUNKU 11/2026", "", "-39.00")
    add("si_codeharbor_12", "2026-12-03", "recurring", "CODEHARBOR.IO 420.00 USD, bought 2 Dec on card *4417",
        "CODEHARBOR INC (SAMPLE)", "-420.00", "USD")
    # The rest of the story's 5,701 for 1-5 Dec is daily card purchases, pinned here so the story adds up.
    known = Decimal("2460.00") + Decimal("39.00") + Decimal("420.00") * RATES["USD"]
    add("si_cards_1_5_dec", "2026-12-05", "estimate", "Card purchases 1-5 Dec (weekday average)", "",
        f"-{Decimal('5701') - known:.2f}")
    add("si_nordwind", "2026-12-07", "receivable",
        "FV 2026/10/044, due 14 Nov, not paid; expected = due date + 23 days average delay",
        "NORDWIND LOGISTIK GMBH (SAMPLE)", "18400.00", "EUR", due_date="2026-11-14", average_delay_days=23,
        stress_date="2026-12-21")
    add("si_zus_11", "2026-12-15", "tax", "SKLADKI ZUS 11/2026", "ZAKLAD UBEZPIECZEN SPOLECZNYCH", "-9400.00")
    add("si_pit4_11", "2026-12-21", "tax", "PIT-4 11/2026 (20 Dec is a Sunday)", "URZAD SKARBOWY LODZ-POLESIE",
        "-3850.00")
    add("si_cit5_11", "2026-12-21", "tax", "CIT-5 ZALICZKA 11/2026 (20 Dec is a Sunday)",
        "URZAD SKARBOWY LODZ-POLESIE", "-7050.00")
    add("si_lakeshore", (AS_OF + timedelta(days=45)).isoformat(), "receivable",
        "FV 2026/11/045, 40,000 USD order, due in 45 days; FX Shield hero case",
        "LAKESHORE ROBOTICS INC (SAMPLE)", "40000.00", "USD", due_date=(AS_OF + timedelta(days=45)).isoformat(),
        profit_pln="8000.00")
    return items


def opening_pln():
    eur = (ACCOUNTS["acc_eur"]["closing"] * RATES["EUR"]).quantize(CENT, ROUND_HALF_UP)
    return ACCOUNTS["acc_pln"]["closing"] + eur


def run(items, nordwind_date=None, skip=()):
    """Daily balances from the as-of date. Within a day, money out goes first ("hit first")."""
    balance, low, ends = opening_pln(), (opening_pln(), AS_OF), {AS_OF: opening_pln()}
    day = AS_OF + timedelta(days=1)
    while day <= date(2026, 12, 31):
        today = [i for i in items if i["id"] not in skip and
                 date.fromisoformat(nordwind_date if (i["id"] == "si_nordwind" and nordwind_date) else i["date"]) == day]
        for sign in (-1, 1):
            for i in today:
                amount = Decimal(i["amount_pln"])
                if (amount < 0) == (sign < 0):
                    balance += amount
            low = min(low, (balance, day))
        ends[day] = balance
        day += timedelta(days=1)
    return ends, low


def check(items, people):
    errors = []
    reimb = -sum(Decimal(i["amount_pln"]) for i in items if i["kind"] == "reimbursement")
    payroll = -sum(Decimal(i["amount_pln"]) for i in items if i["kind"] == "payroll")
    if reimb != Decimal("5169.00"):
        errors.append(f"reimbursements {reimb} != 5169.00")
    if payroll != Decimal("58000.00"):
        errors.append(f"pay run {payroll} != 58000.00")

    ends, low = run(items)
    print(f"{'date':<11} {'story':>9} {'exact':>11} {'diff':>7}  event")
    for day, label, expected in STORY:
        exact = ends[day]
        print(f"{day.isoformat():<11} {expected:>9} {exact:>11} {exact - expected:>7}  {label}")
        if abs(exact - expected) > TOLERANCE:
            errors.append(f"{day}: {exact} vs story {expected}")
    if low[1] != date(2026, 12, 5):
        errors.append(f"lowest point on {low[1]}, story says 2026-12-05")
    _, stress = run(items, nordwind_date="2026-12-21")
    _, before_live = run(items, skip={"si_reimb_rcpt412"})
    for label, got, expected in [("stress low (Nordwind 21 Dec)", stress[0], STRESS_LOW),
                                 ("low before the live receipt", before_live[0], LOW_BEFORE_LIVE_RECEIPT)]:
        print(f"{'':<11} {expected:>9} {got:>11} {got - expected:>7}  {label}")
        if abs(got - expected) > TOLERANCE:
            errors.append(f"{label}: {got} vs story {expected}")

    borsuk = [p for p in people if p["company_id"] == COMPANY_ID]
    roles = sorted(p["role"] for p in borsuk)
    if roles != ["contractor"] * 4 + ["employee"] * 2 + ["owner"]:
        errors.append(f"Borsuk Labs roles {roles}")
    if not any(p["name"] == "Jan Kowalski (SAMPLE)" and p["role"] == "employee" for p in people):
        errors.append("Jan Kowalski (SAMPLE) is not an employee")
    for p in people:
        if not p["email"].endswith(".sample") or "(SAMPLE)" not in p["name"]:
            errors.append(f"{p['id']}: e-mail must end in .sample and name must carry (SAMPLE)")
    if errors:
        raise SystemExit("story check FAILED:\n  " + "\n  ".join(errors))
    print("story check OK")


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"out/{path.name}: {len(data)} entries")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    people = [{k: p[k] for k in ("id", "company_id", "name", "email", "role")} for p in PEOPLE]
    items = story_items()
    write(OUT / "people.json", people)
    write(OUT / "story_items.json", items)
    check(items, people)


if __name__ == "__main__":
    main()
