#!/usr/bin/env python3
"""Spike 01: parse the organisers' pizzeria bank statement, profile it, and
show the CHF booking quirk (CHF amounts inside a EUR account).
Stdlib only. Usage: python3 profile_csv.py <path-to-csv>
"""
import csv, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime, date
from decimal import Decimal

t0 = time.time()
path = sys.argv[1]
RATE_RE = re.compile(r"\(([\d.]+)\s*([A-Z]{3})\s*@\s*([\d.]+)\s*EUR/([A-Z]{3})\)")

def dec(s):  # German number format: 1.234,56
    return Decimal(s.replace(".", "").replace(",", "."))

rows = []
with open(path, encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter=";", quotechar='"'):
        r["date"] = datetime.strptime(r["Booking Date"], "%d.%m.%y").date()
        r["vdate"] = datetime.strptime(r["Value Date"], "%d.%m.%y").date()
        r["amount_raw"] = dec(r["Amount"])
        r["amount_eur"] = r["amount_raw"]
        r["fx_note"] = None
        if r["Currency"] != "EUR":
            m = RATE_RE.search(r["Payment Reference"])
            if not m:
                raise SystemExit(f"non-EUR row without rate in reference: {r}")
            fc_amt, fc, rate, fc2 = Decimal(m[1]), m[2], Decimal(m[3]), m[4]
            assert fc == fc2 == r["Currency"] and fc_amt == abs(r["amount_raw"])
            sign = -1 if r["amount_raw"] < 0 else 1
            r["amount_eur"] = (sign * fc_amt * rate).quantize(Decimal("0.01"))
            r["fx_note"] = f"{fc_amt} {fc} @ {rate} = {abs(r['amount_eur'])} EUR"
        rows.append(r)

rows.sort(key=lambda r: r["date"])
print(f"rows: {len(rows)}  columns: {len(rows[0]) - 5}")
print(f"date range: {rows[0]['date']} .. {rows[-1]['date']}")
print(f"accounts: {Counter(r['Account Number'] for r in rows)}")
print(f"currencies: {Counter(r['Currency'] for r in rows)}")
print(f"info values: {Counter(r['Info'] for r in rows)}")
print(f"booking != value date: {sum(r['date'] != r['vdate'] for r in rows)}")
print(f"empty counterparty account: {sum(not r['Counterparty Account'] for r in rows)}")
dups = Counter((r['date'], r['amount_raw'], r['Beneficiary/Payer'], r['Payment Reference']) for r in rows)
print(f"exact duplicate rows: {sum(c - 1 for c in dups.values() if c > 1)}")

print("\n== by transaction type (count, sum EUR after fix) ==")
by_type = defaultdict(lambda: [0, Decimal(0)])
for r in rows:
    by_type[r["Transaction Type"]][0] += 1
    by_type[r["Transaction Type"]][1] += r["amount_eur"]
for k, (n, s) in sorted(by_type.items(), key=lambda kv: kv[1][1]):
    print(f"{k:32s} {n:5d} {s:14,.2f}")

print("\n== by counterparty (count, sum EUR, min, max, days-of-month seen) ==")
by_cp = defaultdict(list)
for r in rows:
    by_cp[r["Beneficiary/Payer"]].append(r)
for k, rs in sorted(by_cp.items(), key=lambda kv: sum(x["amount_eur"] for x in kv[1])):
    amts = [x["amount_eur"] for x in rs]
    doms = sorted(Counter(x["date"].day for x in rs).items(), key=lambda kv: -kv[1])[:4]
    print(f"{k[:42]:42s} {len(rs):4d} {sum(amts):12,.2f} {min(amts):10,.2f} {max(amts):10,.2f}  dom={doms}")

naive = sum(r["amount_raw"] for r in rows)
fixed = sum(r["amount_eur"] for r in rows)
print("\n== CHF quirk ==")
for r in rows:
    if r["fx_note"]:
        print(f"{r['date']}  raw {r['amount_raw']} {r['Currency']}  ->  {r['amount_eur']} EUR   ({r['fx_note']})")
print(f"naive sum of Amount column (mixing CHF and EUR): {naive:,.2f}")
print(f"sum after converting CHF with the rate in the reference: {fixed:,.2f}")
print(f"difference: {fixed - naive:,.2f}   official year-end: 33,266.35 (docx) / 33,266.34 (chart)")

OFFICIAL_END = Decimal("33266.35")
opening = OFFICIAL_END - fixed
print(f"implied opening balance (official year-end minus fixed sum): {opening:,.2f}  <- NOT present in the CSV")
print("\n== monthly net / inflow / outflow / month-end balance (using implied opening balance) ==")
bal = opening; daily = {}
for r in rows:
    bal += r["amount_eur"]; daily[r["date"]] = bal
months = defaultdict(lambda: [Decimal(0), Decimal(0)])
for r in rows:
    months[r["date"].strftime("%Y-%m")][0 if r["amount_eur"] > 0 else 1] += r["amount_eur"]
run = opening
for m in sorted(months):
    i, o = months[m]; run += i + o
    print(f"{m}  in {i:11,.2f}  out {o:12,.2f}  net {i+o:11,.2f}  end-balance {run:11,.2f}")
lo = min(daily, key=daily.get)
print(f"\nlowest end-of-day balance: {daily[lo]:,.2f} on {lo}")
neg = [d for d in sorted(daily) if daily[d] < 0]
print(f"days with negative end-of-day balance (booking days only): {len(neg)}; first {neg[0]}, last {neg[-1]}")
print(f"balance 2025-06-30: {max((d, b) for d, b in daily.items() if d <= date(2025, 6, 30))[1]:,.2f}")
rev = [r for r in rows if r["amount_eur"] > 0]
gap = [r["date"] for r in rev if date(2025, 5, 25) <= r["date"] <= date(2025, 7, 10)]
print(f"revenue gap: last inflow before shutdown {max(d for d in gap if d < date(2025, 6, 15))}, first after {min(d for d in gap if d > date(2025, 6, 15))}")
print(f"\nelapsed: {time.time() - t0:.2f}s")
