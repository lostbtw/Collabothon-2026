"""The explainable day-by-day cash forecast (#28, D-08). Pure: plain inputs in, a Forecast dict out.

Method "recurring-schedule + weekday-average v1", from the company's as-of date (D-21: only bank lines booked up
to it). The forecast has two parts:

  1. Known and regular (high confidence): recurring series (salaries, taxes, rent, subscriptions), open sales
     invoices at due date + the client's average delay, open bills, reimbursements owed (approved Ledger entries),
     extra inflows and outflows the owner announced.
  2. Everyday flows (low confidence): the trailing 8-week mean per weekday of everything that is not regular
     (taxi, fuel, meals, small purchases; for a shop also its daily card revenue).

Each point carries three balances:
  high     part 1 + expected everyday income, no everyday spending
  balance  part 1 + expected everyday income and spending          (the forecast line; alerts use it)
  low      part 1 + everyday income x 0.5 + everyday spending x 1.5

No LLM, no model: every number is traceable to the rows in `evidence` (D-02).
"""
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .calendar import last_business_day, on_or_after
from .series import Flow, counterparty_key, detect, template, weekday_averages

METHOD = "recurring-schedule + weekday-average v1"
HORIZON_DAYS = 45
BAND = Decimal("0.5")            # everyday flows: low case = spending x 1.5 and income x 0.5
VARIABLE_CONFIDENCE = 0.5
CENT = Decimal("0.01")


def money(value: Decimal, currency: str) -> dict[str, str]:
    return {"amount": f"{Decimal(value).quantize(CENT, ROUND_HALF_UP):.2f}", "currency": currency}


def fmt(value: Decimal) -> str:
    return f"{Decimal(value).quantize(CENT, ROUND_HALF_UP):.2f}"


def shown(value: Decimal, currency: str) -> str:
    return f"{Decimal(value):,.2f} {currency}"


def _link(kind: str, id_: str, label: str, url: str | None = None) -> dict[str, str]:
    out = {"kind": kind, "id": id_, "label": label}
    if url:
        out["url"] = url
    return out


def _txn_link(f: Flow, currency: str) -> dict[str, str]:
    t = f.transaction
    return _link("transaction", t["id"], f"{f.name or f.template or 'Bank line'}, {f.day}, {shown(f.amount, currency)}",
                 f"/transactions/{t['id']}")


def _next_pay_run(as_of: date, country: str) -> date:
    run = last_business_day(as_of.year, as_of.month, country)
    if run <= as_of:
        nxt = (as_of.replace(day=28) + timedelta(days=4)).replace(day=1)
        run = last_business_day(nxt.year, nxt.month, country)
    return run


def inputs_hash(**inputs: Any) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_forecast(*, company: dict, accounts: list[dict], transactions: Iterable[dict], rates: dict[str, Decimal],
                   open_items: Iterable[dict] = (), ledger_entries: Iterable[dict] = (), events: Iterable[dict] = (),
                   invoice_keys: Iterable[str] = (), people_keys: Iterable[str] = (), own_ibans: Iterable[str] = (),
                   own_keys: Iterable[str] = (),
                   horizon_days: int = HORIZON_DAYS, safety_buffer: Decimal | None = None,
                   forecast_id: str | None = None, generated_at: str = "") -> dict[str, Any]:
    """The Forecast (contracts/schemas/forecast.schema.json) of one company.

    company        {id, base_currency, as_of_date, country}
    accounts       Account dicts; only `include_in_liquidity` ones count; `opening_balance` = balance before the
                   first bank line (null = 0)
    transactions   Transaction dicts (any order); lines after the as-of date are ignored (D-21)
    rates          base-currency units per 1 unit of each currency, e.g. {"PLN": 1, "EUR": 4.41}
    open_items     open invoices: {id, kind: receivable|payable, label, key, amount: Money, due_date,
                   delay_days, confidence}
    ledger_entries Ledger entries; approved `reimbursement_liability` ones are paid with the next pay run
    events         owner events (forecast.schema.json#/properties/events/items)
    invoice_keys   counterparties paid by invoice: their bank lines are neither a series nor an average
                   (their open invoices are the forecast), so nothing is counted twice
    people_keys    team members: only their regular payments (salaries) are projected; their irregular ones
                   (reimbursement payouts) come from the Ledger
    own_ibans      the company's own accounts: transfers between them are not flows
    own_keys       the company itself as a counterparty (same purpose, when only the name is known)
    """
    base = company["base_currency"]
    country = company.get("country") or ""
    as_of = date.fromisoformat(str(company["as_of_date"]))
    end = as_of + timedelta(days=horizon_days)
    rate = {k: Decimal(str(v)) for k, v in rates.items()}
    people_keys, invoice_keys = set(people_keys), set(invoice_keys)
    open_items, ledger_entries, events = list(open_items), list(ledger_entries), list(events)
    included, transactions, opening, flows, last_line = _prepare(company, accounts, transactions, rate, own_ibans,
                                                                 own_keys)

    # ---- part 1: recurring series, open invoices, reimbursements, announced flows ------------------------------
    series, rest = detect(flows, as_of, country, loose_keys=invoice_keys)
    variable = [f for f in rest if f.key not in people_keys and f.key not in invoice_keys]
    averages = weekday_averages(variable, as_of)
    certain: dict[date, Decimal] = defaultdict(Decimal)
    components: list[dict[str, Any]] = []

    expected_at: dict[str, date] = {}
    for item in open_items:
        due = date.fromisoformat(item["due_date"])
        delay = int(item.get("delay_days") or 0)
        expected_at[item["id"]] = on_or_after(max(due + timedelta(days=delay), as_of + timedelta(days=1)), country)

    for s in series:
        dates = [d for d in s.dates(as_of, end, country) if not any(  # an open invoice replaces that occurrence
            s.key in (i.get("keys") or [i.get("key")]) and abs((expected_at[i["id"]] - d).days) <= 10 for i in open_items)]
        if not dates:
            continue
        for d in dates:
            certain[d] += s.amount
        not_invoiced = s.key in invoice_keys
        components.append({
            "id": f"c_{s.id}", "label": s.label + (" (expected, not invoiced yet)" if not_invoiced else ""),
            "kind": s.kind, "amount_base": money(s.amount * len(dates), base), "schedule": s.schedule(),
            "dates": [d.isoformat() for d in dates], "confidence": 0.6 if not_invoiced else s.confidence,
            "evidence": [_txn_link(f, base) for f in s.flows[-3:]],
        })

    for item in open_items:
        amount = Decimal(item["amount"]["amount"]) * rate[item["amount"]["currency"]]
        if item["kind"] == "payable":
            amount = -abs(amount)
        due = date.fromisoformat(item["due_date"])
        delay = int(item.get("delay_days") or 0)
        expected = expected_at[item["id"]]
        if expected > end:
            continue
        certain[expected] += amount
        why = f"expected {expected} = due date {due}" + (f" + this client's average delay of {delay} days"
                                                           if delay else "")
        foreign = item["amount"]["currency"] != base
        components.append({
            "id": f"c_{item['id']}", "label": item["label"] + (f", {shown(Decimal(item['amount']['amount']), item['amount']['currency'])}"
                                                              if foreign else ""),
            "kind": "known_receivable" if item["kind"] == "receivable" else "known_payable",
            "amount_base": money(amount, base), "schedule": why, "dates": [expected.isoformat()],
            "confidence": float(item.get("confidence", 0.8)),
            "evidence": [_link("document", item["id"], item["label"], f"/documents/{item['id']}")],
        })

    pay_run = _next_pay_run(as_of, country)
    owed: dict[date, list[dict]] = defaultdict(list)
    for e in ledger_entries:
        if e.get("type") == "reimbursement_liability" and e.get("status") == "approved":
            cash = e.get("cash_date")
            day = on_or_after(date.fromisoformat(cash), country) if cash and cash > as_of.isoformat() else pay_run
            if day <= end:
                owed[day].append(e)
    for day, entries in sorted(owed.items()):
        total = sum(Decimal(e["amount_base"]["amount"]) for e in entries)
        certain[day] += total
        components.append({
            "id": f"c_reimb_{day:%Y%m%d}", "label": f"Reimbursements owed to the team ({len(entries)})",
            "kind": "reimbursement", "amount_base": money(total, base), "schedule": f"with the pay run on {day}",
            "dates": [day.isoformat()], "confidence": 0.9,
            "evidence": [_link("ledger_entry", e["id"], e.get("explanation", e["id"])[:80], f"/ledger/{e['id']}")
                         for e in entries[:5]],
        })

    quiet: dict[date, set[str]] = defaultdict(set)   # days without everyday flows: {"in", "out"}
    for ev in events:
        start, stop = date.fromisoformat(ev["date_from"]), date.fromisoformat(ev["date_to"])
        link = _link("external", ev["id"], f"Owner event: {ev['label']}")
        if ev["effect"] in ("extra_inflow", "extra_outflow") and ev.get("amount"):
            amount = abs(Decimal(ev["amount"]["amount"]) * rate[ev["amount"]["currency"]])
            amount = amount if ev["effect"] == "extra_inflow" else -amount
            if as_of < start <= end:
                certain[start] += amount
                components.append({"id": f"c_{ev['id']}", "label": ev["label"], "kind": "owner_event",
                                   "amount_base": money(amount, base), "schedule": f"on {start}",
                                   "dates": [start.isoformat()], "confidence": 0.9, "evidence": [link]})
            continue
        d = start
        while d <= stop:
            quiet[d] |= {"in", "out"} if ev["effect"] == "no_variable_flows" else {"in"}
            d += timedelta(days=1)

    # ---- part 2 and the daily points -------------------------------------------------------------------------
    var_in = {k: {wd: v for wd, v in per.items() if v > 0} for k, per in averages.items()}
    var_out = {k: {wd: v for wd, v in per.items() if v < 0} for k, per in averages.items()}
    totals = {"in": Decimal(0), "out": Decimal(0)}
    removed = {ev["id"]: Decimal(0) for ev in events}
    balance = high = low = opening
    points = [{"date": as_of.isoformat(), "balance": fmt(opening), "inflow": "0.00", "outflow": "0.00",
               "low": fmt(opening), "high": fmt(opening)}]
    d = as_of
    while d < end:
        d += timedelta(days=1)
        wd = d.weekday()
        vin = sum((per.get(wd, Decimal(0)) for per in var_in.values()), Decimal(0))
        vout = sum((per.get(wd, Decimal(0)) for per in var_out.values()), Decimal(0))
        for ev in events:
            if ev["date_from"] <= d.isoformat() <= ev["date_to"] and ev["effect"] in ("no_variable_flows", "no_revenue"):
                removed[ev["id"]] += -(vin + (vout if ev["effect"] == "no_variable_flows" else 0))
                break
        if "in" in quiet[d]:
            vin = Decimal(0)
        if "out" in quiet[d]:
            vout = Decimal(0)
        totals["in"] += vin
        totals["out"] += vout
        fixed = certain.get(d, Decimal(0))
        balance += fixed + vin + vout
        high += fixed + vin
        low += fixed + vin * (1 - BAND) + vout * (1 + BAND)
        day_in = max(fixed, Decimal(0)) + vin
        day_out = min(fixed, Decimal(0)) + vout
        points.append({"date": d.isoformat(), "balance": fmt(balance), "inflow": fmt(day_in),
                       "outflow": fmt(day_out), "low": fmt(low), "high": fmt(high)})

    top = sorted(((sum(per.values()), k) for k, per in averages.items()), key=lambda x: x[0])
    by_key = defaultdict(list)
    for f in variable:
        by_key[f.key].append(f)
    for side, total, picks in (("out", totals["out"], [k for v, k in top if v < 0][:3]),
                               ("in", totals["in"], [k for v, k in reversed(top) if v > 0][:3])):
        if total == 0:
            continue
        names = ", ".join(by_key[k][-1].name or by_key[k][-1].template for k in picks)
        components.append({
            "id": f"c_everyday_{side}",
            "label": ("Everyday spending" if side == "out" else "Everyday income") + f" (for example {names})",
            "kind": "variable_average", "amount_base": money(total, base),
            "schedule": f"mean per weekday over the {8} weeks up to {as_of}",
            "dates": [], "confidence": VARIABLE_CONFIDENCE,
            "evidence": [_txn_link(by_key[k][-1], base) for k in picks],
        })
    for ev in events:
        if ev["effect"] in ("no_variable_flows", "no_revenue") and removed[ev["id"]]:
            components.append({
                "id": f"c_{ev['id']}", "label": ev["label"], "kind": "owner_event",
                "amount_base": money(removed[ev["id"]], base),
                "schedule": f"{ev['date_from']} to {ev['date_to']}: no everyday "
                            + ("income or spending" if ev["effect"] == "no_variable_flows" else "income"),
                "dates": [], "confidence": 0.9,
                "evidence": [_link("external", ev["id"], f"Owner event: {ev['label']}")],
            })

    accounts_link = [_txn_link(f, base) for f in last_line.values()] or [
        _link("rule", "opening_balance", "No bank line booked yet: opening balance of the accounts")]
    components.insert(0, {
        "id": "c_open", "label": f"Cash today on {len(included)} company account(s)", "kind": "opening_balance",
        "amount_base": money(opening, base), "schedule": None, "dates": [as_of.isoformat()], "confidence": 1.0,
        "evidence": accounts_link,
    })

    # ---- summary ---------------------------------------------------------------------------------------------
    min_balance, first_negative, alerts = summarise(points, as_of, base, safety_buffer)

    assumptions = [f"Only bank lines booked up to {as_of} are used.",
                   "Everyday flows: mean per weekday over the last 8 weeks; the band shows them from 0% "
                   "(high) to 150% of spending and 50% of income (low)."]
    assumptions += [f"1 {c} = {r} {base}" for c, r in sorted(rate.items()) if c != base and (
        any(a["currency"] == c for a in included.values()) or any(i["amount"]["currency"] == c for i in open_items))]
    digest = inputs_hash(as_of=as_of, horizon=horizon_days, rates=rate, buffer=safety_buffer,
                         accounts=sorted((a["id"], json.dumps(a.get("opening_balance"), sort_keys=True))
                                         for a in included.values()),
                         lines=sorted((t["id"], t["amount_base"]["amount"], t["booking_date"]) for t in transactions),
                         items=sorted(json.dumps(i, sort_keys=True, default=str) for i in open_items),
                         ledger=sorted((e["id"], e.get("status"), e.get("cash_date")) for e in ledger_entries),
                         events=sorted(json.dumps(e, sort_keys=True) for e in events),
                         invoice_keys=sorted(invoice_keys), people_keys=sorted(people_keys))
    return {
        "id": forecast_id or f"fc_{company['id']}_{digest[:10]}",
        "company_id": company["id"], "generated_at": generated_at or f"{as_of}T00:00:00Z", "as_of_date": as_of.isoformat(),
        "horizon_days": horizon_days, "base_currency": base, "opening_balance": money(opening, base),
        "safety_buffer": money(safety_buffer, base) if safety_buffer is not None else None,
        "method": METHOD, "points": points, "components": components,
        "min_balance": min_balance, "first_negative_date": first_negative,
        "alerts": alerts, "events": events, "assumptions": assumptions, "scenario_of": None,
        "inputs_hash": digest,
    }


def summarise(points: list[dict], as_of: date, base: str, safety_buffer: Decimal | None = None):
    """(min_balance, first_negative_date, alerts) of daily points; the forecast line is `balance`."""
    low_point = min(points, key=lambda p: (Decimal(p["balance"]), p["date"]))
    negative = [p for p in points if Decimal(p["balance"]) < 0]
    alerts = []
    if negative:
        first = date.fromisoformat(negative[0]["date"])
        run = []
        for p in points:
            if p["date"] < first.isoformat():
                continue
            if Decimal(p["balance"]) >= 0:
                break
            run.append(p)
        days_ahead = (first - as_of).days
        alerts.append({"type": "cash_gap", "severity": "critical" if days_ahead <= 14 else "warning",
                       "date_from": first.isoformat(), "date_to": run[-1]["date"],
                       "max_shortfall": money(-min(Decimal(p["balance"]) for p in run), base),
                       "days_ahead": days_ahead})
    elif safety_buffer is not None and Decimal(low_point["balance"]) < safety_buffer:
        alerts.append({"type": "below_buffer", "severity": "warning", "date_from": low_point["date"],
                       "date_to": None, "max_shortfall": money(safety_buffer - Decimal(low_point["balance"]), base),
                       "days_ahead": (date.fromisoformat(low_point["date"]) - as_of).days})
    min_balance = {"date": low_point["date"], "amount": money(Decimal(low_point["balance"]), base)}
    return min_balance, negative[0]["date"] if negative else None, alerts


def _prepare(company: dict, accounts: list[dict], transactions: Iterable[dict], rate: dict[str, Decimal],
             own_ibans: Iterable[str], own_keys: Iterable[str] = ()):
    """Liquidity accounts, their bank lines up to the as-of date, the balance on it, and the flows that can be
    projected (everything except transfers between the company's own accounts)."""
    as_of = str(company["as_of_date"])
    own_ibans, own_keys = set(own_ibans), set(own_keys)
    included = {a["id"]: a for a in accounts if a.get("include_in_liquidity")}
    lines = [t for t in transactions if t.get("account_id") in included and t["booking_date"] <= as_of]
    opening = Decimal(0)
    for acc in included.values():
        ob = acc.get("opening_balance")
        if ob:
            opening += Decimal(ob["amount"]) * rate[ob["currency"]]
    flows: list[Flow] = []
    last_line: dict[str, Flow] = {}
    for t in sorted(lines, key=lambda t: (t["booking_date"], t["id"])):
        ab = t["amount_base"]
        f = Flow(date.fromisoformat(t["booking_date"]), Decimal(ab["amount"]) * rate[ab["currency"]],
                 counterparty_key(t), t.get("counterparty_name_raw") or "", template(t.get("description")), t)
        opening += f.amount
        last_line[t["account_id"]] = f
        own = t.get("counterparty_account") in own_ibans or f.key in own_keys
        if t.get("transaction_type") != "internal" and not own:
            flows.append(f)
    return included, lines, opening, flows, last_line


def recurring_series_ids(*, company: dict, accounts: list[dict], transactions: Iterable[dict],
                         rates: dict[str, Decimal], own_ibans: Iterable[str] = (),
                         own_keys: Iterable[str] = ()) -> dict[str, str]:
    """transaction id -> recurring_series_id for every bank line in a detected series (written onto
    Transactions; role 3 auto-confirms only lines that carry one)."""
    rate = {k: Decimal(str(v)) for k, v in rates.items()}
    _, _, _, flows, _ = _prepare(company, accounts, transactions, rate, own_ibans, own_keys)
    series, _ = detect(flows, date.fromisoformat(str(company["as_of_date"])), company.get("country") or "")
    return {f.transaction["id"]: s.id for s in series for f in s.flows}
