#!/usr/bin/env python3
"""Spike 05: FX Shield core method on real data.
"We do not predict the rate. We show what you could lose if it moves against you."

Method (historical simulation, no forecast):
  1. Download ~3 years of NBP table-A mid rates (PLN per 1 unit of foreign currency).
  2. For every past day t, take the relative change over the invoice horizon: r = S(t+h)/S(t) - 1.
  3. Apply every r to today's rate -> distribution of plausible outcomes at the due date.
  4. Loss for a RECEIVABLE (we get foreign currency): positive when the rate falls.
     Loss for a PAYABLE   (we pay foreign currency): positive when the rate rises.
  5. Downside = 95th percentile loss, and expected shortfall = mean loss in the worst 10% of scenarios.
     (The plain average is useless: moves go both ways and average out near zero.)
  6. Compare downside with the deal's profit margin and with the cost of a hedge.
Stdlib only. Usage: python3 fx_downside.py
"""
import json, time, urllib.request
from bisect import bisect_right
from datetime import date, timedelta

t0 = time.time()
TODAY = date(2026, 11, 20); YEARS = 3

def nbp_history(cur, start, end):
    out = {}; a = start
    while a <= end:                                   # NBP allows at most 93 days per call
        b = min(a + timedelta(days=90), end)
        url = f"https://api.nbp.pl/api/exchangerates/rates/a/{cur}/{a}/{b}/?format=json"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hackathon-spike/0.1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            for x in json.loads(r.read())["rates"]: out[date.fromisoformat(x["effectiveDate"])] = x["mid"]
        a = b + timedelta(days=1)
    return out

def horizon_changes(hist, h_days):
    days = sorted(hist); res = []
    for d in days:
        target = d + timedelta(days=h_days)
        if target > days[-1]: break
        j = bisect_right(days, target) - 1            # last business day on or before the target
        res.append(hist[days[j]] / hist[d] - 1)
    return res

def pct(sorted_vals, p):
    k = (len(sorted_vals) - 1) * p; f = int(k); c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

def upside(changes, notional, spot, kind):
    sign = -1 if kind == "receivable" else 1
    gains = sorted(max(0.0, -sign * r) * notional * spot for r in changes)
    return pct(gains, 0.95)

def downside(changes, notional, spot, kind):
    """kind: 'receivable' (lose when rate falls) or 'payable' (lose when rate rises). Returns PLN figures."""
    sign = -1 if kind == "receivable" else 1
    losses = sorted(max(0.0, sign * r) * notional * spot for r in changes)
    pnl = [sign * r * notional * spot for r in changes]            # signed: positive = loss
    worst = losses[int(len(losses) * 0.9):]
    return {"p95": pct(losses, 0.95), "es10": sum(worst) / len(worst), "mean_pnl": sum(pnl) / len(pnl),
            "worst": losses[-1], "share_losing": sum(l > 0 for l in losses) / len(losses), "n": len(losses)}

hist = {}
for cur in ("eur", "usd", "chf"):
    hist[cur] = nbp_history(cur, TODAY - timedelta(days=365 * YEARS), TODAY)
    days = sorted(hist[cur])
    print(f"{cur.upper()}: {len(days)} daily rates {days[0]} .. {days[-1]}, today {hist[cur][days[-1]]:.4f}, "
          f"min {min(hist[cur].values()):.4f}, max {max(hist[cur].values()):.4f}")

print("\n== distribution of rate changes by horizon (3 years of history, overlapping windows) ==")
print(f"{'cur':4}{'days':>5}{'n':>6}{'p05':>9}{'median':>9}{'p95':>9}{'mean':>9}")
for cur in ("eur", "usd", "chf"):
    for h in (30, 45, 60, 90):
        ch = sorted(horizon_changes(hist[cur], h))
        print(f"{cur.upper():4}{h:>5}{len(ch):>6}{pct(ch,0.05):>9.2%}{pct(ch,0.5):>9.2%}{pct(ch,0.95):>9.2%}{sum(ch)/len(ch):>9.2%}")

CASES = [  # label, currency, notional, kind, horizon days, deal margin in PLN (owner input or company average)
    ("A  small SaaS bill",                 "usd",   1150, "payable",    30,   None),
    ("B  usual EUR sales invoice",         "eur",  18400, "receivable", 45,  14000),
    ("C  unusually large USD sales order", "usd",  60000, "receivable", 45,  19000),
    ("D  large USD equipment purchase",    "usd",  42000, "payable",    60,  12000),
    ("E  demo case: one-off USD order, thin margin", "usd", 40000, "receivable", 45, 8000),
]
FWD_COST = 0.003      # illustrative bank margin on a forward, share of notional
OPT_COST = 0.012      # illustrative option premium, share of notional
print("\n== downside per invoice (PLN) ==")
for label, cur, n, kind, h, margin in CASES:
    days = sorted(hist[cur]); spot = hist[cur][days[-1]]
    d = downside(horizon_changes(hist[cur], h), n, spot, kind)
    value = n * spot; fwd = value * FWD_COST; opt = value * OPT_COST
    print(f"\n{label}: {n:,} {cur.upper()} {kind}, due in {h} days, worth {value:,.0f} PLN today (rate {spot:.4f})")
    print(f"   scenarios {d['n']}; rate moved against us in {d['share_losing']:.0%} of them; average result {-d['mean_pnl']:+,.0f} PLN (near zero: useless as a risk measure)")
    print(f"   good case (95th percentile gain) {upside(horizon_changes(hist[cur], h), n, spot, kind):,.0f} PLN")
    print(f"   bad case (95th percentile) loss {d['p95']:,.0f} PLN; expected shortfall (mean of worst 10%) {d['es10']:,.0f} PLN; worst seen {d['worst']:,.0f} PLN")
    if margin:
        share = d["es10"] / margin
        print(f"   deal margin {margin:,} PLN -> a bad case eats {share:.0%} of it")
        hedge = share >= 0.25 and fwd < d["es10"]
        print(f"   forward cost (illustrative {FWD_COST:.1%}) {fwd:,.0f} PLN; option premium (illustrative {OPT_COST:.1%}) {opt:,.0f} PLN")
        print(f"   RULE: downside >= 25% of margin AND forward cost < expected shortfall  ->  {'PROPOSE HEDGE (forward)' if hedge else 'HEDGING NOT WORTH IT'}")
    else:
        print(f"   no margin known; owner loss limit 500 PLN -> {'PROPOSE HEDGE' if d['es10'] > 500 else 'HEDGING NOT WORTH IT (say so explicitly)'}")
print(f"\nelapsed: {time.time() - t0:.1f}s")
