#!/usr/bin/env python3
"""Spike 03: can a simple, explainable (non-neural) forecast warn about the
pizzeria's June/July cash gap weeks ahead? Backtest on the organisers' CSV.

Method (deliberately simple, every number traceable to source rows):
  1. Normalise amounts to EUR (CHF fix from spike 01), opening balance 2,500.
  2. Recurring detector per counterparty on history <= as_of:
       - FIXED: monthly/quarterly, same day-of-month, stable amount  -> schedule
       - VARIABLE: everything else -> mean amount per weekday over trailing 8 weeks
  3. Project N days ahead: fixed schedule + weekday averages.
  4. Optional owner-supplied EVENT: "closed from..to" => variable flows are zero.
  5. Report predicted minimum balance, its date, first day below zero, and the
     credit line that would cover the gap with a 10% buffer. Compare with actuals.
Stdlib only. Usage: python3 forecast_backtest.py <csv>
"""
import csv, re, sys, time
from collections import defaultdict
from datetime import datetime, date, timedelta
from statistics import mean, pstdev

t0 = time.time()
RATE_RE = re.compile(r"\(([\d.]+)\s*([A-Z]{3})\s*@\s*([\d.]+)\s*EUR/([A-Z]{3})\)")
OPENING = 2500.00

def load(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            amt = float(r["Amount"].replace(".", "").replace(",", "."))
            if r["Currency"] != "EUR":
                m = RATE_RE.search(r["Payment Reference"])
                amt = round((-1 if amt < 0 else 1) * float(m[1]) * float(m[3]), 2)
            rows.append({"d": datetime.strptime(r["Booking Date"], "%d.%m.%y").date(),
                         "cp": r["Beneficiary/Payer"], "amt": amt})
    return sorted(rows, key=lambda r: r["d"])

def detect(history, as_of):
    """Split counterparties into fixed schedules and weekday-average variable flows."""
    by_cp = defaultdict(list)
    for r in history:
        by_cp[r["cp"]].append(r)
    fixed, variable = [], {}
    for cp, rs in by_cp.items():
        # a counterparty can carry several series (e.g. tax office: monthly + 2 quarterly) -> split by rounded amount
        by_amt = defaultdict(list)
        for r in rs:
            by_amt[round(r["amt"], -1) if abs(r["amt"]) < 4000 or pstdev([x["amt"] for x in rs]) > 100 else "all"].append(r)
        series_ok = True; found = []
        for key, ss in by_amt.items():
            doms = {x["d"].day for x in ss}; months = sorted({(x["d"].year, x["d"].month) for x in ss})
            amts = [x["amt"] for x in ss]
            stable = (pstdev(amts) / abs(mean(amts)) < 0.02) if len(amts) > 1 else False
            if len(ss) >= 2 and len(doms) == 1 and stable and len(months) == len(ss):
                gaps = {(b[0] - a[0]) * 12 + b[1] - a[1] for a, b in zip(months, months[1:])}
                if gaps <= {1} or gaps <= {3}:
                    found.append({"cp": cp, "dom": doms.pop(), "every": gaps.pop(), "amt": round(mean(amts), 2),
                                  "last": ss[-1]["d"], "n": len(ss)})
                    continue
            series_ok = False
        if series_ok:
            fixed += found
        else:
            cutoff = as_of - timedelta(days=56)
            per_wd = defaultdict(float)
            for r in rs:
                if r["d"] > cutoff:
                    per_wd[r["d"].weekday()] += r["amt"]
            variable[cp] = {wd: round(v / 8, 2) for wd, v in per_wd.items()}
    return fixed, variable

def add_months(y, m, k):
    m0 = (m - 1 + k); return y + m0 // 12, m0 % 12 + 1

def project(balance, fixed, variable, as_of, horizon, closed=None):
    out = []; d = as_of
    due = {}
    for f in fixed:
        y, m = f["last"].year, f["last"].month
        while True:
            y, m = add_months(y, m, f["every"]); nd = date(y, m, f["dom"])
            if nd > as_of + timedelta(days=horizon): break
            if nd > as_of: due.setdefault(nd, []).append(f)
    for _ in range(horizon):
        d += timedelta(days=1)
        for f in due.get(d, []): balance += f["amt"]
        if not (closed and closed[0] <= d <= closed[1]):
            for cp, wd in variable.items(): balance += wd.get(d.weekday(), 0.0)
        out.append((d, round(balance, 2)))
    return out

rows = load(sys.argv[1])
def actual_balance(upto):
    return round(OPENING + sum(r["amt"] for r in rows if r["d"] <= upto), 2)
actual_daily = {}
b = OPENING
for r in rows:
    b += r["amt"]; actual_daily[r["d"]] = round(b, 2)
act_min_d = min((d for d in actual_daily if date(2025, 6, 1) <= d <= date(2025, 8, 31)), key=actual_daily.get)
print(f"ACTUAL: min balance {actual_daily[act_min_d]:,.2f} on {act_min_d}; first negative day in June: "
      f"{min(d for d in actual_daily if d >= date(2025, 6, 1) and actual_daily[d] < 0)}")

SHUTDOWN = (date(2025, 6, 1), date(2025, 6, 30))   # what the data really shows (zero revenue AND zero purchases all June)
for as_of in [date(2025, 4, 30), date(2025, 5, 15), date(2025, 5, 31)]:
    hist = [r for r in rows if r["d"] <= as_of]
    fixed, variable = detect(hist, as_of)
    bal = actual_balance(as_of)
    print(f"\n=== as of {as_of}: balance {bal:,.2f}; {len(fixed)} fixed series, {len(variable)} variable counterparties ===")
    if as_of == date(2025, 5, 15):
        for f in sorted(fixed, key=lambda f: f["amt"]):
            print(f"   fixed: {f['cp'][:40]:40s} {f['amt']:10,.2f} every {f['every']} mo on day {f['dom']} (seen {f['n']}x)")
        for cp, wd in variable.items():
            print(f"   variable: {cp[:40]:40s} avg/week {sum(wd.values()):10,.2f}")
    for label, closed in [("no event known", None), ("owner told us: closed 1-30 June", SHUTDOWN)]:
        proj = project(bal, fixed, variable, as_of, 75, closed)
        lo = min(proj, key=lambda x: x[1]); neg = [d for d, v in proj if v < 0]
        line = -lo[1] * 1.10 if lo[1] < 0 else 0
        err = lo[1] - actual_daily[act_min_d]
        print(f" [{label}] predicted min {lo[1]:,.2f} on {lo[0]}; first day < 0: {neg[0] if neg else 'never'}"
              f"; lead time to first negative day: {(neg[0] - as_of).days if neg else '-'} d"
              f"; suggested credit line (gap +10%): {line:,.0f} EUR; error vs actual min: {err:+,.2f}")
print(f"\nelapsed: {time.time() - t0:.2f}s")
