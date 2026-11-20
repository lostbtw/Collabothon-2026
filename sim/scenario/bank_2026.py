#!/usr/bin/env python3
"""Borsuk Labs (SAMPLE) bank lines, 1 Jan - 20 Nov 2026, in the pizzeria CSV format.

Routine rows (Jan-Oct, plus daily card purchases in November) come from a
seeded generator. The November story rows are written by hand. The closing
balance on 20 Nov is fixed by the liquidity story (24,730.15 PLN and
3,100.00 EUR); the opening balance on 1 Jan is computed backwards from it.
Fixed seed, so the output is byte-identical on every run.

Usage: python3 sim/scenario/bank_2026.py
Output: sim/scenario/out/bank_<account>.csv
"""
import csv
import json
import math
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from world import ACCOUNTS, COMPANY, OUT, PERSON, bank_name

SEED = 2026
START, END = date(2026, 1, 1), date(2026, 11, 20)

# Same columns, order, encoding and number format as the organisers'
# pizzeria CSV (pizzeria-amalfi-bank-statement-2025-v6.csv).
COLUMNS = [
    "Account Number", "Booking Date", "Value Date", "Transaction Type",
    "Payment Reference", "Beneficiary/Payer", "Counterparty Account",
    "Bank Code", "Amount", "Currency", "Info",
]

# Invented BICs ("SMPL" bank) per IBAN country; card lines have none.
BIC = {"PL": "SMPLPLPWXXX", "DE": "SMPLDEFFXXX"}

# Polish public holidays 2026 that fall on a weekday.
HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 6), date(2026, 5, 1),
            date(2026, 6, 4), date(2026, 11, 11)}

US_LODZ = ("URZAD SKARBOWY LODZ-POLESIE", "PL00999900000000000000099002")
ZUS = ("ZAKLAD UBEZPIECZEN SPOLECZNYCH", "PL00999900000000000000099001")
COWORKING = ("COWORKING PIOTRKOWSKA SP Z O O (SAMPLE)", "PL00999900000000000000020001")
ACCOUNTING = ("BIURO RACHUNKOWE KALINOWSKA (SAMPLE)", "PL00999900000000000000020002")
LINGUA = ("LINGUA BRIDGE GMBH (SAMPLE)", "DE00SAMPLE0000000000000001")
NORDWIND = ("NORDWIND LOGISTIK GMBH (SAMPLE)", "DE00SAMPLE0000000000")
MEBLOSTYL = ("MEBLOSTYL SP Z O O (SAMPLE)", "PL00999900000000000000030003")
PIEKARNIA = ("PIEKARNIA ZLOTY KLOS SP Z O O (SAMPLE)", "PL00999900000000000000030001")
KADROWNIA = ("KADROWNIA SP Z O O (SAMPLE)", "PL00999900000000000000030002")

# Pay run on the last bank day: 2 employees, 4 B2B contractors, owner's board fee = 58,000.00.
# (person id, type, reference, amount); story_2026.py uses the same list for 30 Nov.
PAY_RUN_PLAN = [
    ("per_jan", "SALARY PAYMENT", "WYNAGRODZENIE {mm}", "8200.00"),
    ("per_marta", "SALARY PAYMENT", "WYNAGRODZENIE {mm}", "7400.00"),
    ("per_anna", "SUPPLIER PAYMENT", "FV {m}/{mm} USLUGI PROGRAMISTYCZNE", "9800.00"),
    ("per_piotr", "SUPPLIER PAYMENT", "FV {m}/{mm} USLUGI PROGRAMISTYCZNE", "10500.00"),
    ("per_karolina", "SUPPLIER PAYMENT", "FV {m}/{mm} PROJEKTOWANIE UX", "8600.00"),
    ("per_michal", "SUPPLIER PAYMENT", "FV {m}/{mm} TESTY QA", "6500.00"),
    ("per_tomek", "SALARY PAYMENT", "WYNAGRODZENIE ZARZADU {mm}", "7000.00"),
]
PAY_RUN = [(bank_name(pid), PERSON[pid]["iban"], ttype, ref, amount)
           for pid, ttype, ref, amount in PAY_RUN_PLAN]

# SaaS on company card *4417: (purchase day, descriptor, payer, amount, currency). 1,150 USD + 180 EUR.
SAAS = [
    (2, "CODEHARBOR.IO* SAN FRANCISCO", "CODEHARBOR INC (SAMPLE)", "420.00", "USD"),
    (4, "CLOUDNEST HOSTING* AMSTERDAM", "CLOUDNEST BV (SAMPLE)", "380.00", "USD"),
    (5, "NOTEFORGE EU* DUBLIN", "NOTEFORGE LTD (SAMPLE)", "120.00", "EUR"),
    (7, "MAILFOX* ATLANTA", "MAILFOX INC (SAMPLE)", "89.00", "USD"),
    (12, "TASKLOOM.COM", "TASKLOOM INC (SAMPLE)", "136.00", "USD"),
    (13, "SIGNDESK BV AMSTERDAM", "SIGNDESK BV (SAMPLE)", "60.00", "EUR"),
    (17, "LOGBEAR INC*", "LOGBEAR INC (SAMPLE)", "80.00", "USD"),
    (19, "PIXELBOARD.COM* SAN FRANCISCO", "PIXELBOARD INC (SAMPLE)", "45.00", "USD"),
]

# Daily purchases (descriptor, payer, min, max). Descriptors ending in ZAM/NADANIE get an order number (M9).
CARD_PLN = [
    ("PALIWEX 112 LODZ", "PALIWEX SP Z O O (SAMPLE)", 120, 340),
    ("NORDPETRO STACJA 21 LODZ", "NORDPETRO S.A. (SAMPLE)", 110, 320),
    ("BISTRO PIOTRKOWSKA 90 LODZ", "BISTRO PIOTRKOWSKA 90 (SAMPLE)", 45, 420),
    ("SUSHI KAMIEN LODZ", "SUSHI KAMIEN (SAMPLE)", 60, 380),
    ("KAWIARNIA ZIARNO LODZ", "KAWIARNIA ZIARNO (SAMPLE)", 12, 75),
    ("MARKET KOSZYK 24 LODZ", "KOSZYK 24 SP Z O O (SAMPLE)", 25, 210),
    ("BIUROSFERA.PL ZAM", "BIUROSFERA SP Z O O (SAMPLE)", 40, 520),
    ("KURIERON*NADANIE", "KURIERON SP Z O O (SAMPLE)", 14, 62),
    ("TAXIGO*TRIP LODZ", "TAXIGO SP Z O O (SAMPLE)", 18, 95),
    ("PARKUJ.PL LODZ", "PARKUJ.PL SP Z O O (SAMPLE)", 3, 28),
    ("SKLEPIK.PL*ZAM", "SKLEPIK.PL SP Z O O (SAMPLE)", 30, 640),
    ("RAILEXPRESS BILETY", "RAILEXPRESS S.A. (SAMPLE)", 39, 165),
    ("DOMENOWO.PL", "DOMENOWO SP Z O O (SAMPLE)", 19, 149),
]
CARD_EUR = [  # EUR debit card *2290 on acc_eur (Nordwind visits, EU shops)
    ("BAHNREISE*TICKET BERLIN", "BAHNREISE GMBH (SAMPLE)", 19, 149),
    ("HOTEL KANAL HAMBURG", "HOTEL KANAL GMBH (SAMPLE)", 89, 260),
    ("COWORK SPREE BERLIN DAYPASS", "COWORK SPREE GMBH (SAMPLE)", 25, 45),
    ("EUROSHOP ONLINE*ORDER", "EUROSHOP ONLINE BV (SAMPLE)", 15, 220),
    ("CAFE HAFEN HAMBURG", "CAFE HAFEN (SAMPLE)", 6, 48),
    ("TAXI ZENTRALE HAMBURG", "TAXI ZENTRALE HH (SAMPLE)", 14, 55),
]
CARD_OWNER = [  # owner's private spending on *9021
    ("SPOZYWCZY U ZOSI LODZ", "SPOZYWCZY U ZOSI (SAMPLE)", 25, 260),
    ("MARKET KOSZYK 24 LODZ", "KOSZYK 24 SP Z O O (SAMPLE)", 20, 190),
    ("APTEKA POD ORLEM LODZ", "APTEKA POD ORLEM (SAMPLE)", 12, 140),
    ("KINO WIDOK LODZ", "KINO WIDOK (SAMPLE)", 28, 96),
    ("RESTAURACJA STARY RYNEK LODZ", "RESTAURACJA STARY RYNEK (SAMPLE)", 70, 380),
    ("PALIWEX 87 LODZ", "PALIWEX SP Z O O (SAMPLE)", 150, 330),
    ("KSIEGARNIA SLOWNIK LODZ", "KSIEGARNIA SLOWNIK (SAMPLE)", 25, 120),
    ("SKLEPIK.PL*ZAM", "SKLEPIK.PL SP Z O O (SAMPLE)", 30, 450),
    ("KAWIARNIA ZIARNO LODZ", "KAWIARNIA ZIARNO (SAMPLE)", 10, 45),
]
# Irregular purchases 3-9k, one per month: (kind, descriptor or reference, payer, account, min, max)
IRREGULAR = [
    ("card", "ELEKTROMARKT LODZ PORT", "ELEKTROMARKT POLSKA S.A. (SAMPLE)", "", 3200, 8900),
    ("card", "DEVCAMP.PL*BILETY", "DEVCAMP SP Z O O (SAMPLE)", "", 3000, 5600),
    ("transfer", "FV EM/{m}/2026 KRZESLA BIUROWE", "ERGO MEBLE SP Z O O (SAMPLE)", "PL00999900000000000000020010",
     3000, 7200),
    ("transfer", "FV LEX/{m}/2026 OBSLUGA PRAWNA", "KANCELARIA PRAWNA LEX (SAMPLE)", "PL00999900000000000000020011",
     3500, 6500),
]
# M4: private purchases from the company account (the 4th is the spa in November).
PRIVATE_ON_COMPANY = {
    3: ("PERFUMERIA AROMA LODZ", "PERFUMERIA AROMA (SAMPLE)", "289.00"),
    6: ("SKLEP ZOOLOGICZNY PUPIL LODZ", "SKLEP ZOOLOGICZNY PUPIL (SAMPLE)", "164.50"),
    8: ("BIURO PODROZY SLONCE LODZ", "BIURO PODROZY SLONCE (SAMPLE)", "1850.00"),
}
# Nordwind: invoices due on the 14th of odd months, paid late; delays average exactly 23 days.
NORDWIND_INVOICES = [(1, 21), (3, 25), (5, 22), (7, 24), (9, 23)]

# November story rows, hand-written: (booking, value, type, payer, account, reference, amount).
NOV_ROWS = {
    "acc_pln": [
        ("02.11", "02.11", "RENT PAYMENT", *COWORKING, "CZYNSZ 11/2026 BIURO 4B FV CW/11/2026/017", "-2460.00"),
        ("02.11", "02.11", "BANK FEE", "", "", "OPLATA ZA PROWADZENIE RACHUNKU 10/2026", "-39.00"),
        ("03.11", "02.11", "GIRO CARD PAYMENT", "CODEHARBOR INC (SAMPLE)", "",
         "CODEHARBOR.IO* SAN FRANCISCO 420.00 USD KARTA *4417", ("420.00", "4.0702")),
        ("04.11", "04.11", "INCOMING TRANSFER", *PIEKARNIA, "FV 2026/10/041", "8610.00"),
        ("05.11", "04.11", "GIRO CARD PAYMENT", "CLOUDNEST BV (SAMPLE)", "",
         "CLOUDNEST HOSTING* AMSTERDAM 380.00 USD KARTA *4417", ("380.00", "4.0815")),
        ("05.11", "05.11", "GIRO CARD PAYMENT", "PALIWEX SP Z O O (SAMPLE)", "",
         "PALIWEX 112 LODZ KARTA *4417", "-248.60"),
        ("06.11", "05.11", "GIRO CARD PAYMENT", "NOTEFORGE LTD (SAMPLE)", "",
         "NOTEFORGE EU* DUBLIN 120.00 EUR KARTA *4417", ("120.00", "4.4612")),
        ("09.11", "07.11", "GIRO CARD PAYMENT", "MAILFOX INC (SAMPLE)", "",
         "MAILFOX* ATLANTA 89.00 USD KARTA *4417", ("89.00", "4.0566")),
        ("10.11", "10.11", "SUPPLIER PAYMENT", *ACCOUNTING, "FV 112/11/2026 OBSLUGA KSIEGOWA 11/2026", "-1230.00"),
        ("10.11", "09.11", "GIRO CARD PAYMENT", "BISTRO PIOTRKOWSKA 90 (SAMPLE)", "",
         "BISTRO PIOTRKOWSKA 90 LODZ KARTA *4417", "-312.00"),
        ("12.11", "10.11", "GIRO CARD PAYMENT", "ELEKTROMARKT POLSKA S.A. (SAMPLE)", "",
         "ELEKTROMARKT LODZ PORT KARTA *4417", "-4899.00"),
        ("12.11", "12.11", "GIRO CARD PAYMENT", "TASKLOOM INC (SAMPLE)", "",
         "TASKLOOM.COM 136.00 USD KARTA *4417", ("136.00", "4.0921")),
        # M4: private purchase paid from the company account.
        ("13.11", "12.11", "GIRO CARD PAYMENT", "SPA PERLA (SAMPLE)", "", "SPA PERLA LODZ KARTA *4417", "-450.00"),
        ("13.11", "13.11", "GIRO CARD PAYMENT", "SIGNDESK BV (SAMPLE)", "",
         "SIGNDESK BV AMSTERDAM 60.00 EUR KARTA *4417", ("60.00", "4.4730")),
        ("16.11", "16.11", "DIRECT DEBIT", *ZUS, "SKLADKI ZUS 10/2026 NIP 9990000014", "-9400.00"),
        ("16.11", "14.11", "GIRO CARD PAYMENT", "BIUROSFERA SP Z O O (SAMPLE)", "",
         "BIUROSFERA.PL ZAM 55120 KARTA *4417", "-386.40"),
        ("17.11", "17.11", "INCOMING TRANSFER", *KADROWNIA, "ZAPLATA ZA FV 2026/10/043", "4920.00"),
        ("18.11", "17.11", "GIRO CARD PAYMENT", "LOGBEAR INC (SAMPLE)", "",
         "LOGBEAR INC* 80.00 USD KARTA *4417", ("80.00", "4.0477")),
        # Tax office series kept separate (payroll withholding vs CIT advance).
        ("20.11", "20.11", "TAX OFFICE TRANSFER", *US_LODZ, "PIT-4 10/2026 NIP 9990000014", "-3850.00"),
        ("20.11", "20.11", "TAX OFFICE TRANSFER", *US_LODZ, "CIT-5 ZALICZKA 10/2026 NIP 9990000014", "-7050.00"),
        # Same line as contracts/fixtures/transaction.json txn_731 (balance after = 24,730.15).
        ("20.11", "19.11", "GIRO CARD PAYMENT", "PIXELBOARD INC (SAMPLE)", "",
         "PIXELBOARD.COM* SAN FRANCISCO 45.00 USD KARTA *4417", "-180.62"),
    ],
    "acc_eur": [
        ("02.11", "02.11", "BANK FEE", "", "", "ACCOUNT FEE EUR 10/2026", "-5.00"),
        ("16.11", "16.11", "INTERNATIONAL WIRE TRANSFER", *LINGUA, "INV LB-2026-0912 TRANSLATION DE", "-240.00"),
    ],
    "acc_owner": [
        ("03.11", "02.11", "GIRO CARD PAYMENT", "SPOZYWCZY U ZOSI (SAMPLE)", "",
         "SPOZYWCZY U ZOSI LODZ KARTA *9021", "-187.45"),
        # M3: company costs paid with the owner's private card.
        ("06.11", "05.11", "GIRO CARD PAYMENT", "RAILEXPRESS S.A. (SAMPLE)", "",
         "RAILEXPRESS BILETY LODZ-WARSZAWA KARTA *9021", "-139.80"),
        ("13.11", "12.11", "GIRO CARD PAYMENT", "HOTEL CENTRUM WARSZAWA (SAMPLE)", "",
         "HOTEL CENTRUM WARSZAWA KARTA *9021", "-489.00"),
        ("13.11", "13.11", "GIRO CARD PAYMENT", "TAXIGO SP Z O O (SAMPLE)", "", "TAXIGO*TRIP WARSZAWA KARTA *9021",
         "-46.30"),
        ("16.11", "14.11", "GIRO CARD PAYMENT", "KSIEGARNIA SLOWNIK (SAMPLE)", "",
         "KSIEGARNIA SLOWNIK LODZ KARTA *9021", "-64.90"),
        ("18.11", "17.11", "GIRO CARD PAYMENT", "FIGMENT DESIGN INC (SAMPLE)", "",
         "FIGMENT DESIGN* 15.00 USD KARTA *9021", ("15.00", "4.1100")),
    ],
}

CENT = Decimal("0.01")


def money(x):
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def is_bank_day(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def on_or_after(d):
    while not is_bank_day(d):
        d += timedelta(days=1)
    return d


def next_bank_day(d):
    return on_or_after(d + timedelta(days=1))


def last_bank_day(m):
    d = date(2026, m + 1, 1) - timedelta(days=1)
    while not is_bank_day(d):
        d -= timedelta(days=1)
    return d


NBP_RATES = json.loads((Path(__file__).parent / "nbp_rates.json").read_text(encoding="utf-8"))


def mid_rate(cur, d):
    """Real NBP table A mid rate (sim/scenario/nbp_rates.json) of the last table published on or before `d`:
    the rate a card purchase on day `d` is priced from. After the last table the last one is used."""
    table = NBP_RATES[cur]
    day = d
    for _ in range(400):
        rate = table.get(day.isoformat())
        if rate is not None:
            return float(rate)
        if day < date.fromisoformat(min(table)):
            return float(table[min(table)])
        day -= timedelta(days=1)
    raise KeyError(f"no NBP {cur} rate on or before {d}")


def card_rate(cur, d):
    """The NBP rate a foreign card purchase on day `d` is priced from: the last table published BEFORE `d`.
    That is the PL-FX-01 rate the matcher converts the document with, so bank amount / (document x rate) is the
    card spread alone and never the day-to-day move of the real rate (a real jump of 1.5% plus a 3% spread
    would leave the matcher's band)."""
    return mid_rate(cur, d - timedelta(days=1))


def fx_amount(amount, rate):
    return -(Decimal(amount) * Decimal(rate)).quantize(CENT, ROUND_HALF_UP)


def german(amount):
    """Decimal -> pizzeria number format, e.g. -1299.5 -> '-1299,50' (no thousands separator)."""
    return f"{amount:.2f}".replace(".", ",")


def purchase_doc(number, issue, due, line=None):
    """Invoice data for a purchase paid by bank transfer (Borsuk Labs is the buyer)."""
    return {"direction": "purchase", "pay": "transfer", "number": number, "issue": issue, "due": due, "line": line}


def sale_doc(number, issue, due):
    """Invoice data for a sale (Borsuk Labs is the seller), paid by bank transfer."""
    return {"direction": "sale", "pay": "transfer", "number": number, "issue": issue, "due": due}


class Book:
    """Collects rows per account: (booking, value, type, reference, payer, account, amount).

    A row can carry `doc`: the data of the invoice behind it (used by fa3_2026.py). Documents
    never consume random numbers, so adding them does not change the bank lines.
    """

    def __init__(self):
        self.rows = {acc: [] for acc in ACCOUNTS}
        self.docs = []

    def add(self, acc, booking, ttype, ref, payer, cp_acc, amount, value=None, doc=None):
        row = (booking, value or booking, ttype, ref, payer, cp_acc, money(amount))
        self.rows[acc].append(row)
        if doc is not None:
            self.docs.append({"party": payer, "party_account": cp_acc, **doc,
                              "bank": {"account": acc, "row_index": len(self.rows[acc]) - 1,
                                       "booking_date": row[0], "value_date": row[1],
                                       "reference": ref, "amount": row[6], "currency": ACCOUNTS[acc]["currency"]}})

    def ordered(self, acc):
        """Rows in booking order, as (entry reference, insertion index, row).

        The Sandbox Bank (sim/bank) loads a CSV in the same order and numbers the lines E000000001, ...
        """
        rows = sorted(enumerate(self.rows[acc]), key=lambda x: (x[1][0], x[0]))
        return [(f"E{n:09d}", i, row) for n, (i, row) in enumerate(rows, start=1)]

    def entry_reference(self, acc, row_index):
        if not hasattr(self, "_refs"):
            self._refs = {(a, i): ref for a in self.rows for ref, i, _ in self.ordered(a)}
        return self._refs[(acc, row_index)]

    def card(self, acc, purchase, descriptor, payer, amount, card, doc=None):
        if doc is not None:
            doc = {"direction": "purchase", "pay": "card", "issue": purchase, "paid": purchase, **doc}
        self.add(acc, next_bank_day(purchase), "GIRO CARD PAYMENT", f"{descriptor} KARTA *{card}", payer, "",
                 -money(amount), value=purchase, doc=doc)


def noisy(rng, descriptor):
    if descriptor.endswith(("ZAM", "NADANIE")):
        return f"{descriptor} {rng.randint(10000, 99999)}"
    return descriptor


def random_day(rng, m, first=1, last=None):
    last = last or (date(2026, m + 1, 1) - timedelta(days=1)).day
    return date(2026, m, rng.randint(first, last))


def daily_cards(book, rng, m, count, last_day=None):
    for _ in range(count):
        desc, payer, lo, hi = rng.choice(CARD_PLN)
        book.card("acc_pln", random_day(rng, m, last=last_day), noisy(rng, desc), payer, rng.uniform(lo, hi), "4417",
                  doc={"daily": True})
    for _ in range(max(1, count // 6)):
        desc, payer, lo, hi = rng.choice(CARD_EUR)
        book.card("acc_eur", random_day(rng, m, last=last_day), desc, payer, rng.uniform(lo, hi), "2290")
    for _ in range(count // 2):
        desc, payer, lo, hi = rng.choice(CARD_OWNER)
        book.card("acc_owner", random_day(rng, m, last=last_day), noisy(rng, desc), payer, rng.uniform(lo, hi),
                  "9021")


def generate_month(book, rng, m):
    mm = f"{m:02d}/2026"
    prev = f"{m - 1:02d}/2026" if m > 1 else "12/2025"
    inv = f"2026/{m - 1:02d}" if m > 1 else "2025/12"
    pln, eur, owner = "acc_pln", "acc_eur", "acc_owner"

    # Recurring payments.
    first = on_or_after(date(2026, m, 1))
    book.add(pln, first, "RENT PAYMENT",
             f"CZYNSZ {mm} BIURO 4B FV CW/{mm}/{m + 6:03d}", *COWORKING, "-2460.00",
             doc=purchase_doc(f"CW/{mm}/{m + 6:03d}", date(2026, m, 1), first, f"Najem stanowiska biurowego {mm}"))
    book.add(pln, first, "BANK FEE", f"OPLATA ZA PROWADZENIE RACHUNKU {prev}", "", "", "-39.00")
    book.add(eur, first, "BANK FEE", f"ACCOUNT FEE EUR {prev}", "", "", "-5.00")
    day10 = on_or_after(date(2026, m, 10))
    book.add(pln, day10, "SUPPLIER PAYMENT",
             f"FV {100 + m}/{mm} OBSLUGA KSIEGOWA {mm}", *ACCOUNTING, "-1230.00",
             doc=purchase_doc(f"{100 + m}/{mm}", date(2026, m, 3), day10, f"Obsługa księgowa {mm}"))
    book.add(pln, on_or_after(date(2026, m, 15)), "DIRECT DEBIT", f"SKLADKI ZUS {prev} NIP 9990000014", *ZUS,
             -rng.randrange(910000, 970001, 100) / 100)
    day20 = on_or_after(date(2026, m, 20))
    book.add(pln, day20, "TAX OFFICE TRANSFER", f"PIT-4 {prev} NIP 9990000014", *US_LODZ,
             -rng.randrange(3600, 4101, 10))
    book.add(pln, day20, "TAX OFFICE TRANSFER", f"CIT-5 ZALICZKA {prev} NIP 9990000014", *US_LODZ,
             -rng.randrange(6500, 7601, 10))
    book.add(pln, on_or_after(date(2026, m, 25)), "TAX OFFICE TRANSFER", f"VAT-7 {prev} NIP 9990000014", *US_LODZ,
             -rng.randrange(12000, 16001, 10))
    book.add(eur, on_or_after(date(2026, m, 16)), "INTERNATIONAL WIRE TRANSFER",
             f"INV LB-2026-{m:02d}{rng.randint(10, 99)} TRANSLATION DE", *LINGUA, -rng.randrange(180, 321, 5))

    # SaaS on the company card at card rates (M6: 0.5-4.5% spread over mid).
    for day, desc, payer, amount, cur in SAAS:
        purchase = date(2026, m, day)
        rate = Decimal(f"{card_rate(cur, purchase) * (1 + rng.uniform(0.005, 0.045)):.4f}")
        book.card(pln, purchase, f"{desc} {amount} {cur}", payer, -fx_amount(amount, rate), "4417")

    # Pay run on the last bank day, plus reimbursements owed to the team (M1/M2).
    payday = last_bank_day(m)
    for name, iban, ttype, ref, amount in PAY_RUN:
        ref = ref.format(m=m, mm=mm)
        doc = None
        if ttype == "SUPPLIER PAYMENT":  # B2B contractor invoice; salaries have no invoice
            number, line = ref[3:].split(" ", 1)
            doc = purchase_doc(number, date(2026, m, 25), payday, line.capitalize())
        book.add(pln, payday, ttype, ref, name, iban, f"-{amount}", doc=doc)
    book.add(owner, payday, "INCOMING TRANSFER", f"WYNAGRODZENIE ZARZADU {mm}", COMPANY,
             ACCOUNTS[pln]["iban"], PAY_RUN[-1][4])
    for name, iban, *_ in rng.sample(PAY_RUN[:6], rng.randint(1, 4)):
        book.add(pln, payday, "OUTGOING TRANSFER", f"ZWROT KOSZTOW {mm} WG ZESTAWIENIA", name, iban,
                 -rng.randrange(12000, 180001, 1) / 100)

    # Clients (PLN): invoice for the previous month, gross = net x 1.23.
    # Sales fall through the year (x1.18 in Jan -> x0.77 in Oct): the cash gap builds up.
    trend = Decimal("1.225") - Decimal("0.045") * m

    def gross(lo, hi, step):
        return (rng.randrange(lo, hi + 1, step) * trend / 100).quantize(Decimal("1")) * 100 * Decimal("1.23")

    issued = date(2026, m, 1) - timedelta(days=1)  # invoices for the previous month, issued on its last day
    book.add(pln, on_or_after(date(2026, m, 4) + timedelta(days=rng.randint(0, 5))), "INCOMING TRANSFER",
             f"FV {inv}/041", *PIEKARNIA, gross(10000, 16000, 100),
             doc=sale_doc(f"{inv}/041", issued, date(2026, m, 4)))
    book.add(pln, on_or_after(date(2026, m, 15) + timedelta(days=rng.randint(0, 4))), "INCOMING TRANSFER",
             f"ZAPLATA ZA FV {inv}/043", *KADROWNIA, gross(6000, 10000, 100),
             doc=sale_doc(f"{inv}/043", issued, date(2026, m, 15)))
    book.add(pln, on_or_after(date(2026, m, 27)), "INCOMING TRANSFER", f"FV {inv}/042", *MEBLOSTYL,
             gross(30000, 40000, 500), doc=sale_doc(f"{inv}/042", issued, date(2026, m, 27)))

    # Irregular purchase 3-9k.
    kind, text, payer, cp_acc, lo, hi = rng.choice(IRREGULAR)
    if kind == "card":
        book.card(pln, random_day(rng, m), text, payer, rng.randrange(lo, hi + 1, 1), "4417", doc={})
    else:
        day = on_or_after(random_day(rng, m, last=26))
        ref = text.format(m=m)
        book.add(pln, day, "SUPPLIER PAYMENT", ref, payer, cp_acc, -rng.randrange(lo, hi + 1, 10),
                 doc=purchase_doc(ref[3:].split(" ", 1)[0], day - timedelta(days=7), day))
    if m in PRIVATE_ON_COMPANY:
        desc, payer, amount = PRIVATE_ON_COMPANY[m]
        book.card(pln, date(2026, m, 14), desc, payer, amount, "4417")

    # Owner's account: subscriptions and phone (private), Figment design tool (M3: company cost).
    book.card(owner, date(2026, m, 3), "SILOWNIA FORMA LODZ", "SILOWNIA FORMA (SAMPLE)", "149.00", "9021")
    book.card(owner, date(2026, m, 8), "STREAMFLIX*SUBSKRYPCJA", "STREAMFLIX LTD (SAMPLE)", "49.00", "9021")
    book.add(owner, on_or_after(date(2026, m, 22)), "DIRECT DEBIT", f"ABONAMENT {mm} NR KLIENTA 4471902",
             "TELEFONIA ZASIEG S.A. (SAMPLE)", "PL00999900000000000000020020", "-89.00")
    figment = date(2026, m, 17)
    rate = Decimal(f"{card_rate('USD', figment) * 1.03:.4f}")
    book.card(owner, figment, "FIGMENT DESIGN* 15.00 USD", "FIGMENT DESIGN INC (SAMPLE)",
              -fx_amount("15.00", rate), "9021")
    if m == 5:  # M3: client trip to Warsaw on the owner's card; invoices made out to the company
        book.card(owner, date(2026, 5, 19), "RAILEXPRESS BILETY LODZ-WARSZAWA", "RAILEXPRESS S.A. (SAMPLE)",
                  "139.80", "9021", doc={"messiness": ["M3"]})
        book.card(owner, date(2026, 5, 19), "HOTEL CENTRUM WARSZAWA", "HOTEL CENTRUM WARSZAWA (SAMPLE)",
                  "455.00", "9021", doc={"messiness": ["M3"]})
        book.card(owner, date(2026, 5, 20), "TAXIGO*TRIP WARSZAWA", "TAXIGO SP Z O O (SAMPLE)", "38.70", "9021",
                  doc={"messiness": ["M3"]})

    daily_cards(book, rng, m, rng.randint(34, 42))


def generate_nordwind(book, rng):
    """Nordwind pays EUR late; the next bank day most of it is converted to PLN."""
    for due_month, delay in NORDWIND_INVOICES:
        issue = f"2026/{due_month - 1:02d}" if due_month > 1 else "2025/12"
        amount = Decimal(rng.randrange(18000, 22001, 50))
        paid = on_or_after(date(2026, due_month, 14) + timedelta(days=delay))
        due = date(2026, due_month, 14)
        book.add("acc_eur", paid, "INCOMING TRANSFER", f"INV {issue}/044 BORSUK LABS", *NORDWIND, amount,
                 doc=sale_doc(f"{issue}/044", due - timedelta(days=30), due))
        convert = (amount - 500) // 100 * 100
        day = next_bank_day(paid)
        rate = Decimal(f"{mid_rate('EUR', day) * 0.996:.4f}")
        ref = f"PRZEWALUTOWANIE EUR/PLN KURS {str(rate).replace('.', ',')}"
        book.add("acc_eur", day, "INTERNAL TRANSFER", ref, COMPANY, ACCOUNTS["acc_pln"]["iban"], -convert)
        book.add("acc_pln", day, "INTERNAL TRANSFER", ref, COMPANY, ACCOUNTS["acc_eur"]["iban"], convert * rate)


def card_doc(currency=None, gross=None, **extra):
    """Invoice data for a hand-written November card line; foreign ones keep their original amount."""
    doc = {"direction": "purchase", "pay": "card", **extra}
    if currency:
        doc.update(currency=currency, gross=Decimal(gross), foreign=True)
    return doc


# Documents behind the hand-written November rows, by reference. Rows not listed have no document
# (bank fees, ZUS, taxes, the spa (M4) and the owner's private purchases).
NOV_DOCS = {
    # October invoices paid in November.
    "FV 2026/10/041": sale_doc("2026/10/041", date(2026, 10, 31), date(2026, 11, 4)),
    "ZAPLATA ZA FV 2026/10/043": sale_doc("2026/10/043", date(2026, 10, 31), date(2026, 11, 15)),
    "CZYNSZ 11/2026 BIURO 4B FV CW/11/2026/017": purchase_doc(
        "CW/11/2026/017", date(2026, 11, 1), date(2026, 11, 2), "Najem stanowiska biurowego 11/2026"),
    "FV 112/11/2026 OBSLUGA KSIEGOWA 11/2026": purchase_doc(
        "112/11/2026", date(2026, 11, 3), date(2026, 11, 10), "Obsługa księgowa 11/2026"),
    "CODEHARBOR.IO* SAN FRANCISCO 420.00 USD KARTA *4417": card_doc("USD", "420.00"),
    "CLOUDNEST HOSTING* AMSTERDAM 380.00 USD KARTA *4417": card_doc("USD", "380.00"),
    "NOTEFORGE EU* DUBLIN 120.00 EUR KARTA *4417": card_doc("EUR", "120.00"),
    "MAILFOX* ATLANTA 89.00 USD KARTA *4417": card_doc("USD", "89.00"),
    "TASKLOOM.COM 136.00 USD KARTA *4417": card_doc("USD", "136.00"),
    "SIGNDESK BV AMSTERDAM 60.00 EUR KARTA *4417": card_doc("EUR", "60.00"),
    "LOGBEAR INC* 80.00 USD KARTA *4417": card_doc("USD", "80.00"),
    "PIXELBOARD.COM* SAN FRANCISCO 45.00 USD KARTA *4417": card_doc("USD", "45.00"),
    "PALIWEX 112 LODZ KARTA *4417": card_doc(),
    "BISTRO PIOTRKOWSKA 90 LODZ KARTA *4417": card_doc(),
    # These two also arrive as FA(3) XML from KSeF (and as a PDF by e-mail: M5).
    "ELEKTROMARKT LODZ PORT KARTA *4417": card_doc(ksef=True, line="Laptop 14 cali"),
    "BIUROSFERA.PL ZAM 55120 KARTA *4417": card_doc(ksef=True),
    "INV LB-2026-0912 TRANSLATION DE": {
        "direction": "purchase", "pay": "transfer", "number": "LB-2026-0912", "issue": date(2026, 11, 2),
        "due": date(2026, 11, 16), "currency": "EUR", "gross": Decimal("240.00"), "foreign": True,
        "line": "Translation EN-DE, product documentation"},
    # M3: company costs on the owner's private card, invoices made out to the company.
    "RAILEXPRESS BILETY LODZ-WARSZAWA KARTA *9021": card_doc(messiness=["M3"]),
    "HOTEL CENTRUM WARSZAWA KARTA *9021": card_doc(messiness=["M3"]),
    "TAXIGO*TRIP WARSZAWA KARTA *9021": card_doc(messiness=["M3"]),
    "FIGMENT DESIGN* 15.00 USD KARTA *9021": card_doc("USD", "15.00", messiness=["M3"]),
}


def _invented_mid(cur, d):
    """The invented curve the hand-written November card rates were tuned on. Kept only to recover each row's
    card spread (its rate over this curve), so the row keeps its spread on top of the real NBP rate."""
    a, b = {"EUR": (4.33, 4.41), "USD": (3.98, 4.06)}[cur]
    t = (d - START).days / (END - START).days
    return a + (b - a) * t + 0.015 * math.sin(d.toordinal() / 9)


def story_card_amount(foreign, tuned_rate, cur, day):
    """PLN amount of a hand-written foreign card row: the real card_rate() of the purchase day plus the row's spread."""
    spread = float(tuned_rate) / _invented_mid(cur, day) - 1
    return fx_amount(foreign, Decimal(f"{card_rate(cur, day) * (1 + spread):.4f}"))


def add_november(book, rng):
    for acc, rows in NOV_ROWS.items():
        for booking, value, ttype, payer, cp_acc, ref, amount in rows:
            d = lambda s: date(2026, int(s[3:]), int(s[:2]))  # noqa: E731
            if isinstance(amount, tuple):
                cur = "EUR" if " EUR " in f" {ref} " else "USD"
                amount = story_card_amount(*amount, cur, d(value))
            doc = NOV_DOCS.get(ref)
            if doc is not None:
                doc = dict(doc)
                if doc["pay"] == "card":
                    doc.update(issue=d(value), paid=d(value))
            book.add(acc, d(booking), ttype, ref, payer, cp_acc, amount, value=d(value), doc=doc)
    # Daily purchases 1-18 Nov, booked by 19 Nov, so the PIXELBOARD line stays last.
    daily_cards(book, rng, 11, rng.randint(22, 26), last_day=18)


def check(acc, rows):
    for booking, value, *_ in rows:
        assert START <= value <= booking <= END and is_bank_day(booking), (acc, booking, value)


def build():
    """Generate every bank line (and the invoice data behind it). Same seed -> same result."""
    rng = random.Random(SEED)
    book = Book()
    for m in range(1, 11):
        generate_month(book, rng, m)
    generate_nordwind(book, rng)
    add_november(book, rng)
    return book


def main():
    book = build()

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for acc, rows in book.rows.items():
        meta = ACCOUNTS[acc]
        check(acc, rows)
        rows = [row for _, _, row in book.ordered(acc)]  # booking order, same as the Sandbox Bank
        net = sum(r[6] for r in rows)
        opening = meta["opening"] if "opening" in meta else meta["closing"] - net
        balance, low = opening, (opening, START)
        for r in rows:
            balance += r[6]
            low = min(low, (balance, r[0]))
        assert low[0] >= 0, (acc, low)
        if "closing" in meta:
            assert balance == meta["closing"], (acc, balance)

        path = OUT / f"bank_{acc}.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\n")
            w.writerow(COLUMNS)
            for booking, value, ttype, ref, payer, cp_acc, amount in reversed(rows):  # newest first
                w.writerow([meta["iban"], booking.strftime("%d.%m.%y"), value.strftime("%d.%m.%y"), ttype, ref,
                            payer, cp_acc, BIC.get(cp_acc[:2], ""), german(amount), meta["currency"],
                            "Transaction booked"])
        total += len(rows)
        print(f"{path.name}: {len(rows)} rows, opening {opening} -> closing {balance} {meta['currency']}, "
              f"lowest {low[0]} on {low[1]}")
    print(f"total: {total} rows")


if __name__ == "__main__":
    main()
