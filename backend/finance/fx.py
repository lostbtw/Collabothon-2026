"""FX Shield (#47): what an open foreign-currency invoice could lose if the exchange rate moves against the company,
and the facts a model needs to judge whether that loss is large and critical for this company. Pure functions: no
database, no LLM (D-02). The code measures and states facts; the model (backend/agents/fx.py) judges.

There is no profit per deal (one invoice or purchase has none) and no fixed threshold of "large": a company's money in
varies a lot from month to month, so the facts give the model the company's own figures month by month and a list of
reference amounts to compare the loss with (the weakest month, a typical month, the safety buffer, the cash held). The
model decides what is large, which reference fits, and whether to hedge. The reference amounts and the shares are
computed here, so no number the owner sees comes from a model.

Method (role 4 spec #4, spike 05). "We do not predict the rate. We show what you could lose if it moves against you."
  1. Expected cash date = due date + the client's average delay (as in the forecast); horizon h = days to it.
  2. Net exposure: invoices of the opposite direction in the same currency, expected within FX_NET_WINDOW_DAYS,
     offset it; a payable is also covered by the balance held in that currency. A receivable is not: holding the
     currency adds to its risk. Covered to within FX_NATURAL_SHARE -> naturally hedged, nothing to buy.
  3. Every historical h-day change r = S(t+h)/S(t) - 1 of the NBP mid rate over the last 3 years (~700 scenarios).
  4. Loss = value x max(0, -r) for a receivable, value x max(0, +r) for a payable. Bad case = 95th percentile;
     expected shortfall = mean of the worst 10%. The plain average is near zero and is shown only to say so.
  5. Company facts: money in and out for each of the last FX_CONTEXT_MONTHS full months, reference amounts, and the
     forecast's lowest balance from the payment date on, with and without the bad case. A negative balance is
     undesirable but not critical (a credit line covers it).
  6. Hedge terms: payable 100% on the due date; on-time client 100% on the due date; late client
     FX_LATE_HEDGE_RATIO on the expected date. Prices are illustrative, not an offer.
"""
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from .calendar import on_or_after
from .settings import (FX_CONTEXT_MONTHS, FX_FORWARD_COST, FX_HISTORY_DAYS, FX_LATE_DAYS, FX_LATE_HEDGE_RATIO,
                       FX_MIN_HISTORY, FX_NATURAL_SHARE, FX_NET_WINDOW_DAYS, FX_OPTION_COST)

CENT = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
P95 = Decimal("0.95")
NOT_THE_COMPANYS_FLOWS = {"owner_private"}  # categories that are not money of the business


def money(value: Decimal | str, currency: str) -> dict[str, str]:
    """Money as in the contracts: decimal string with 2 places plus currency (hard rule 6)."""
    return {"amount": f"{Decimal(value).quantize(CENT, ROUND_HALF_UP):.2f}", "currency": currency}


def history_window(rates: Mapping[str, str], as_of: date, days: int = FX_HISTORY_DAYS) -> list[tuple[date, Decimal]]:
    """(day, PLN per unit) of the last `days` before the as-of date, oldest first. Tables of later days are ignored,
    so the numbers do not move when the connector stores a newer table."""
    last = as_of - timedelta(days=1)
    first = last - timedelta(days=days)
    out = []
    for day, rate in rates.items():
        d = date.fromisoformat(day)
        if first <= d <= last:
            out.append((d, Decimal(rate)))
    return sorted(out)


def rate_changes(history: list[tuple[date, Decimal]], horizon_days: int) -> list[Decimal]:
    """Every historical change over `horizon_days` calendar days: r = S(t+h)/S(t) - 1, S(t+h) being the last
    published rate on or before t+h."""
    days = [d for d, _ in history]
    out = []
    for d, rate in history:
        target = d + timedelta(days=horizon_days)
        if target > days[-1]:
            break
        later = history[bisect_right(days, target) - 1][1]
        out.append(later / rate - 1)
    return out


def percentile(sorted_values: list[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between the two nearest ranks (as spike 05)."""
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def downside(changes: list[Decimal], value: Decimal, direction: str) -> dict[str, Any]:
    """Losses and gains of `value` (base currency) over the scenarios. All amounts positive except average_result."""
    sign = -1 if direction == "receivable" else 1
    losses = sorted(max(Decimal(0), sign * r) * value for r in changes)
    gains = sorted(max(Decimal(0), -sign * r) * value for r in changes)
    worst = losses[len(losses) * 9 // 10:]
    return {"scenarios": len(changes),
            "bad_case_p95": percentile(losses, P95),
            "expected_shortfall": sum(worst, Decimal(0)) / len(worst),
            "good_case_p95": percentile(gains, P95),
            "average_result": sum((-sign * r * value for r in changes), Decimal(0)) / len(changes)}


def expected_date(item: dict, as_of: date, country: str) -> date:
    """When the money moves: due date + the client's average delay, never before tomorrow (as in the forecast)."""
    delay = int(item.get("delay_days") or 0) if item["kind"] == "receivable" else 0
    due = date.fromisoformat(item["due_date"])
    return on_or_after(max(due + timedelta(days=delay), as_of + timedelta(days=1)), country)


def balances(accounts: Iterable[dict], transactions: Iterable[dict], as_of: date) -> dict[str, Decimal]:
    """Balance held per currency on the as-of date (accounts counted in liquidity only)."""
    held: dict[str, Decimal] = {}
    lines = list(transactions)
    for acc in accounts:
        if not acc.get("include_in_liquidity", True) or not acc.get("opening_balance"):
            continue
        booked = sum((Decimal(t["amount_base"]["amount"]) for t in lines
                      if t.get("account_id") == acc["id"] and t["booking_date"] <= as_of.isoformat()), Decimal(0))
        held[acc["currency"]] = held.get(acc["currency"], Decimal(0)) + Decimal(acc["opening_balance"]["amount"]) + booked
    return held


def company_facts(inputs: dict, forecast: dict) -> dict[str, Any]:
    """The size and the cash of the company, from its own data. Money in and out are given month by month for the last
    FX_CONTEXT_MONTHS full months (bank lines in the base currency; transfers between its own accounts and the owner's
    private spending are not counted): they vary, so there is no single average. `references` are amounts the loss
    can be compared with; the model picks one."""
    company = inputs["company"]
    as_of = date.fromisoformat(company["as_of_date"])
    base = company["base_currency"]
    rates = {k: Decimal(v) for k, v in inputs["rates"].items()}
    this_month = as_of.isoformat()[:7]
    flows: dict[str, list[Decimal]] = {}
    for t in inputs["transactions"]:
        month = t["booking_date"][:7]
        if month >= this_month or t.get("transaction_type") == "internal" or t.get("category") in NOT_THE_COMPANYS_FLOWS:
            continue
        value = Decimal(t["amount_base"]["amount"]) * rates.get(t["amount_base"]["currency"], Decimal(1))
        flows.setdefault(month, [Decimal(0), Decimal(0)])[0 if value > 0 else 1] += abs(value)
    months = sorted(flows)[-FX_CONTEXT_MONTHS:]
    ins, outs = [flows[m][0] for m in months], [flows[m][1] for m in months]
    cash = sum((v * rates.get(c, Decimal(1)) for c, v in balances(inputs["accounts"], inputs["transactions"],
                                                                 as_of).items()), Decimal(0))
    buffer = forecast.get("safety_buffer")
    references = []
    if ins:
        references += [
            {"id": "money_in_weakest_month", "label": f"money in during your weakest of the last {len(ins)} months",
             "amount": money(min(ins), base)},
            {"id": "money_in_median_month", "label": "money in during a typical month (the median)",
             "amount": money(median(ins), base)},
            {"id": "money_out_median_month", "label": "money out during a typical month (the median)",
             "amount": money(median(outs), base)}]
    if buffer:
        references.append({"id": "safety_buffer", "label": "your safety buffer", "amount": buffer})
    if cash > 0:
        references.append({"id": "cash_today", "label": "the cash you hold today", "amount": money(cash, base)})
    return {"months": [{"month": m, "money_in": money(flows[m][0], base), "money_out": money(flows[m][1], base)}
                       for m in months],
            "money_in_strongest_month": money(max(ins), base) if ins else None,
            "references": references, "safety_buffer": buffer, "lowest_forecast_balance": forecast["min_balance"]}


def hedge_terms(item: dict, net: Decimal, spot: Decimal, base: str, expected: date) -> dict[str, Any]:
    """The forward this invoice would need: share, date, rate and illustrative prices."""
    late = item["kind"] == "receivable" and int(item.get("delay_days") or 0) > FX_LATE_DAYS
    ratio = FX_LATE_HEDGE_RATIO if late else Decimal(1)
    currency = item["amount"]["currency"]
    notional = net * ratio
    hedged_value = notional * spot
    selling = item["kind"] == "receivable"
    forward_rate = spot * (1 - FX_FORWARD_COST) if selling else spot * (1 + FX_FORWARD_COST)
    return {"ratio": f"{ratio:.1f}", "value_date": expected.isoformat(),  # on-time: expected = the due date
            "notional": money(notional, currency),
            "sell_currency": currency if selling else base, "buy_currency": base if selling else currency,
            "forward_rate": f"{forward_rate.quantize(RATE_PLACES, ROUND_HALF_UP)}",
            "forward_cost": money(hedged_value * FX_FORWARD_COST, base),
            "option_cost": money(hedged_value * FX_OPTION_COST, base),
            "with_forward": money(notional * forward_rate, base)}


def cash_after(points: list[dict], expected: date, loss: Decimal, base: str) -> dict[str, Any]:
    """The forecast's lowest balance from the payment date on, and with the bad case's loss taken off it."""
    after = [p for p in points if p["date"] >= expected.isoformat()] or points[-1:]
    low = min(after, key=lambda p: Decimal(p["balance"]))
    balance = Decimal(low["balance"])
    return {"lowest_balance_after_payment": {"date": low["date"], "balance": money(balance, base)},
            "lowest_balance_after_payment_with_bad_case": {"date": low["date"], "balance": money(balance - loss, base)},
            "already_negative_after_payment": balance < 0,
            "bad_case_takes_balance_below_zero": balance - loss < 0 and loss > 0}


def loss_against_references(loss: Decimal, company: dict[str, Any]) -> list[dict[str, Any]]:
    """The loss as a share of each reference amount (computed here, so the model only quotes it)."""
    out = []
    for ref in company["references"]:
        amount = Decimal(ref["amount"]["amount"])
        if amount > 0:
            share = loss / amount
            out.append({**ref, "loss_share": f"{share.quantize(Decimal('0.0001'), ROUND_HALF_UP)}",
                        "loss_share_percent": f"{share * 100:.1f}"})
    return out


def assess(item: dict, *, as_of: date, country: str, base: str, spot: Decimal, history: list[tuple[date, Decimal]],
           open_items: list[dict], held: Mapping[str, Decimal], company: dict[str, Any],
           points: list[dict]) -> dict[str, Any] | None:
    """One open foreign-currency invoice -> its facts (the /fx/exposure item, the card's numbers and what the model
    judges). `status` is "open", "naturally_hedged" or (plan 005) "hedged". None when there is too little rate
    history for its currency."""
    if len(history) < FX_MIN_HISTORY:
        return None
    currency = item["amount"]["currency"]
    amount = Decimal(item["amount"]["amount"])
    expected = expected_date(item, as_of, country)
    opposite = sum((Decimal(o["amount"]["amount"]) for o in open_items
                    if o["id"] != item["id"] and o["amount"]["currency"] == currency and o["kind"] != item["kind"]
                    and abs((expected_date(o, as_of, country) - expected).days) <= FX_NET_WINDOW_DAYS), Decimal(0))
    cover = opposite + (max(held.get(currency, Decimal(0)), Decimal(0)) if item["kind"] == "payable" else Decimal(0))
    net = max(amount - cover, Decimal(0))
    out: dict[str, Any] = {
        "document_id": item["id"], "label": item["label"], "direction": item["kind"],
        "amount": money(amount, currency), "covered": money(min(cover, amount), currency),
        "net_amount": money(net, currency), "spot": f"{spot}", "value_today_base": money(net * spot, base),
        "expected_cash_date": expected.isoformat(), "horizon_days": (expected - as_of).days,
        "history_first": history[0][0].isoformat(), "history_last": history[-1][0].isoformat(),
        "history_days": len(history), "company": company}
    if item.get("locked"):  # an executed FX forward fixed its rate (engine.fx_locks): nothing left to judge
        return {**out, "status": "hedged", "locked": item["locked"], "scenarios": 0, "loss_vs_references": []}
    if net <= amount * FX_NATURAL_SHARE:
        return {**out, "status": "naturally_hedged", "scenarios": 0, "loss_vs_references": []}
    value = net * spot
    d = downside(rate_changes(history, out["horizon_days"]), value, item["kind"])
    shortfall = d["expected_shortfall"].quantize(CENT, ROUND_HALF_UP)
    return {**out, "status": "open", "scenarios": d["scenarios"],
            "bad_case_p95": money(-d["bad_case_p95"], base), "expected_shortfall": money(-shortfall, base),
            "good_case_p95": money(d["good_case_p95"], base), "average_result": money(d["average_result"], base),
            "loss_vs_references": loss_against_references(shortfall, company),
            **cash_after(points, expected, shortfall, base), "hedge": hedge_terms(item, net, spot, base, expected)}


def assess_company(inputs: dict, histories: Mapping[str, Mapping[str, str]], forecast: dict) -> list[dict[str, Any]]:
    """Every open foreign-currency invoice of a company (the forecast's inputs, see engine.load_inputs, and the forecast
    built from them), soonest first. `histories`: {currency: {day: base-currency units per unit}}."""
    company = inputs["company"]
    as_of = date.fromisoformat(company["as_of_date"])
    base, country = company["base_currency"], company.get("country", "PL")
    rates = {k: Decimal(v) for k, v in inputs["rates"].items()}
    items = [i for i in inputs["open_items"] if i["kind"] in ("receivable", "payable")]
    held = balances(inputs["accounts"], inputs["transactions"], as_of)
    facts = company_facts(inputs, forecast)
    out = []
    for item in items:
        currency = item["amount"]["currency"]
        if currency == base or currency not in rates:
            continue
        found = assess(item, as_of=as_of, country=country, base=base, spot=rates[currency],
                       history=history_window(histories.get(currency, {}), as_of), open_items=items, held=held,
                       company=facts, points=forecast["points"])
        if found:
            out.append(found)
    return sorted(out, key=lambda a: (a["expected_cash_date"], a["document_id"]))
