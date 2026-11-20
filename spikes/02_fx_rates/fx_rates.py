#!/usr/bin/env python3
"""Spike 02: exchange-rate APIs with no key.
 - NBP (Polish central bank) table A mid rate, incl. the Polish tax rule helper:
   "average NBP rate of the last business day BEFORE the transaction date".
 - ECB reference rates via frankfurter (ECB data, no key).
Stdlib only. Usage: python3 fx_rates.py
"""
import json, time, urllib.request, urllib.error
from datetime import date, timedelta

def get(url):
    t = time.time()
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hackathon-spike/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read()), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, None, time.time() - t

def nbp_mid(cur, d):
    return get(f"https://api.nbp.pl/api/exchangerates/rates/a/{cur}/{d.isoformat()}/?format=json")

def nbp_rate_for_tax(cur, tx_date):
    """Last published table-A rate strictly before tx_date (one range call, pick the last row)."""
    start = tx_date - timedelta(days=10)
    end = tx_date - timedelta(days=1)
    code, body, dt = get(f"https://api.nbp.pl/api/exchangerates/rates/a/{cur}/{start}/{end}/?format=json")
    last = body["rates"][-1]
    return last["effectiveDate"], last["mid"], last["no"], dt

print("== NBP single day (business day) ==")
code, body, dt = nbp_mid("eur", date(2026, 11, 18)); print(code, body and body["rates"], f"{dt:.2f}s")
print("== NBP on a Sunday (expect 404 -> must walk back) ==")
code, body, dt = nbp_mid("eur", date(2026, 11, 15)); print(code, body, f"{dt:.2f}s")
print("== Tax rule helper: rate of last business day BEFORE the transaction date ==")
for cur, d in [("eur", date(2026, 11, 16)), ("usd", date(2026, 11, 12)), ("chf", date(2025, 6, 16)), ("eur", date(2026, 1, 2))]:
    eff, mid, no, dt = nbp_rate_for_tax(cur, d)
    print(f"tx {d} ({d.strftime('%a')}) {cur.upper()}: use {mid} from {eff} table {no}  ({dt:.2f}s)")
print("== NBP whole table A for latest day (all currencies in one call) ==")
code, body, dt = get("https://api.nbp.pl/api/exchangerates/tables/a/?format=json")
print(code, body[0]["no"], body[0]["effectiveDate"], len(body[0]["rates"]), "currencies", f"{dt:.2f}s")
print("== ECB reference rates (frankfurter) EUR->CHF,PLN,USD latest and time series ==")
for url in ["https://api.frankfurter.dev/v1/latest?base=EUR&symbols=CHF,PLN,USD",
            "https://api.frankfurter.dev/v1/2025-06-01..2025-06-30?base=CHF&symbols=EUR"]:
    code, body, dt = get(url)
    if body and "rates" in body and "start_date" in body:
        ks = sorted(body["rates"]); print(code, f"{len(ks)} days", ks[0], body["rates"][ks[0]], "..", ks[-1], body["rates"][ks[-1]], f"{dt:.2f}s")
    else:
        print(code, body, f"{dt:.2f}s")
print("== ECB official SDMX API (data-api.ecb.europa.eu) CHF daily, June 2025 ==")
t = time.time()
req = urllib.request.Request("https://data-api.ecb.europa.eu/service/data/EXR/D.CHF.EUR.SP00.A?startPeriod=2025-06-13&endPeriod=2025-06-17&format=csvdata", headers={"User-Agent": "hackathon-spike/0.1"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        lines = r.read().decode().splitlines()
        hdr = lines[0].split(","); i, j = hdr.index("TIME_PERIOD"), hdr.index("OBS_VALUE")
        print(r.status, [(l.split(",")[i], l.split(",")[j]) for l in lines[1:]], f"{time.time()-t:.2f}s")
except Exception as e:
    print("ECB SDMX failed:", repr(e))
