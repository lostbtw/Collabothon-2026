"""FX Shield (#47): what an open foreign-currency invoice could lose if the exchange rate moves against the company,
set against the profit on the deal, and whether a hedge is worth it. Pure functions: no database, no LLM (D-02).

Method (role 4 spec #4, spike 05). "We do not predict the rate. We show what you could lose if it moves against you."
  1. Expected cash date = due date + the client's average delay (as in the forecast); horizon h = days to it.
  2. Net exposure: invoices of the opposite direction in the same currency, expected within FX_NET_WINDOW_DAYS,
     offset it; a payable is also covered by the balance held in that currency. A receivable is not: holding the
     currency adds to its risk. Covered to within FX_NATURAL_SHARE -> naturally hedged, nothing to buy.
  3. Every historical h-day change r = S(t+h)/S(t) - 1 of the NBP mid rate over the last 3 years (~700 scenarios).
  4. Loss = value x max(0, -r) for a receivable, value x max(0, +r) for a payable. Bad case = 95th percentile;
     expected shortfall = mean of the worst 10%. The plain average is near zero and is shown only to say so.
  5. Profit on the deal: the owner's figure, else the average margin x value; a payable has none (loss limit).
  6. Hedge only if the forward costs at most FX_COST_MAX_SHARE of the shortfall AND the shortfall is at least
     FX_PROFIT_SHARE of the profit or above the loss limit. Otherwise "not worth it".
  7. Hedge terms: payable 100% on the due date; on-time client 100% on the due date; late client
     FX_LATE_HEDGE_RATIO on the expected date. Prices are illustrative, not an offer.
"""
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .calendar import on_or_after
from .settings import (FX_COST_MAX_SHARE, FX_DEFAULT_MARGIN, FX_FORWARD_COST, FX_HISTORY_DAYS, FX_LATE_DAYS,
                       FX_LATE_HEDGE_RATIO, FX_MAX_MARGIN, FX_MENTION_NATURAL, FX_MENTION_SHARE, FX_MIN_HISTORY,
                       FX_MIN_MARGIN_LINES, FX_NATURAL_SHARE, FX_NET_WINDOW_DAYS, FX_OPTION_COST, FX_PROFIT_SHARE)

CENT = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
P95 = Decimal("0.95")
REVENUE = "revenue_services"
NOT_OPERATING = {REVENUE, "owner_private", "financing", "investment_outflow", "taxes"}  # not costs of the business


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


def average_margin(transactions: Iterable[dict], as_of: date, days: int = 365) -> tuple[Decimal, str]:
    """(margin, where it comes from): (income - business costs) / income of the categorised bank lines of the last
    `days`. Too little data, or a margin outside (0, FX_MAX_MARGIN], gives FX_DEFAULT_MARGIN from the settings."""
    first, last = (as_of - timedelta(days=days)).isoformat(), as_of.isoformat()
    lines = [t for t in transactions if t.get("category") and first < t["booking_date"] <= last]
    revenue = sum((Decimal(t["amount_base"]["amount"]) for t in lines
                   if t["category"] == REVENUE and Decimal(t["amount_base"]["amount"]) > 0), Decimal(0))
    costs = sum((-Decimal(t["amount_base"]["amount"]) for t in lines
                 if t["category"] not in NOT_OPERATING and Decimal(t["amount_base"]["amount"]) < 0), Decimal(0))
    default = f"default margin {FX_DEFAULT_MARGIN:.0%} from the settings"
    if len(lines) < FX_MIN_MARGIN_LINES or revenue <= 0:
        return FX_DEFAULT_MARGIN, f"{default}: too few categorised bank lines to measure yours"
    span = (date.fromisoformat(max(t["booking_date"] for t in lines))
            - date.fromisoformat(min(t["booking_date"] for t in lines))).days
    if span < 90:
        return FX_DEFAULT_MARGIN, f"{default}: categorised bank lines cover only {span} days"
    margin = (revenue - costs) / revenue
    if not Decimal(0) < margin <= FX_MAX_MARGIN:
        return FX_DEFAULT_MARGIN, f"{default}: your categorised bank lines give {margin:.0%}, outside 0-{FX_MAX_MARGIN:.0%}"
    return margin, f"average margin of your categorised bank lines over the last 12 months: {margin:.1%}"


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


def verdict(shortfall: Decimal, profit: Decimal | None, loss_limit: Decimal, forward_cost: Decimal) -> tuple[str, str]:
    """(verdict, the rule that decided it) - step 6 of the method."""
    if forward_cost > shortfall * FX_COST_MAX_SHARE:
        return "not_worth_it", f"the forward would cost more than {FX_COST_MAX_SHARE:.0%} of the possible loss"
    if profit is not None and profit > 0 and shortfall >= profit * FX_PROFIT_SHARE:
        return "hedge_proposed", f"the possible loss is at least {FX_PROFIT_SHARE:.0%} of the profit on the deal"
    if shortfall > loss_limit:
        return "hedge_proposed", "the possible loss is above the loss limit"
    return "not_worth_it", (f"the possible loss is under {FX_PROFIT_SHARE:.0%} of the profit and under the loss limit"
                            if profit else "the possible loss is under the loss limit")


def assess(item: dict, *, as_of: date, country: str, base: str, spot: Decimal, history: list[tuple[date, Decimal]],
           open_items: list[dict], held: Mapping[str, Decimal], owner_profit: dict | None,
           margin: tuple[Decimal, str], loss_limit: Decimal) -> dict[str, Any] | None:
    """One open foreign-currency invoice -> its FX Shield assessment (the /fx/exposure item plus the card's numbers).
    None when there is too little rate history for its currency."""
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
        "history_days": len(history), "loss_limit": money(loss_limit, base)}
    if net <= amount * FX_NATURAL_SHARE:
        return {**out, "verdict": "naturally_hedged", "scenarios": 0,
                "mention": amount * spot >= loss_limit * FX_MENTION_NATURAL,
                "rule": f"{currency} invoices and balances on the other side cover this one"}
    value = net * spot
    d = downside(rate_changes(history, out["horizon_days"]), value, item["kind"])
    if item["kind"] == "payable":
        profit, source, note = None, "loss_limit", "a purchase has no profit of its own: compared with the loss limit"
    elif owner_profit:
        profit, source, note = Decimal(owner_profit["amount"]), "owner", "profit on this deal as you entered it"
    else:
        profit, source, note = margin[0] * value, "average_margin", margin[1]
    hedge = hedge_terms(item, net, spot, base, expected)
    shortfall = d["expected_shortfall"].quantize(CENT, ROUND_HALF_UP)
    decided, rule = verdict(shortfall, profit, loss_limit, Decimal(hedge["forward_cost"]["amount"]))
    return {**out, "scenarios": d["scenarios"],
            "bad_case_p95": money(-d["bad_case_p95"], base), "expected_shortfall": money(-shortfall, base),
            "good_case_p95": money(d["good_case_p95"], base), "average_result": money(d["average_result"], base),
            "deal_profit": money(profit, base) if profit is not None else None, "profit_source": source,
            "profit_note": note,
            "share_of_profit": f"{(shortfall / profit).quantize(Decimal('0.0001'), ROUND_HALF_UP)}" if profit else None,
            "hedge": hedge, "verdict": decided, "rule": rule,
            # worth a card in the inbox: every proposal; "not worth it" only when the owner would otherwise wonder
            "mention": decided == "hedge_proposed" or shortfall >= loss_limit * FX_MENTION_SHARE}


def assess_company(inputs: dict, histories: Mapping[str, Mapping[str, str]], owner_profits: Mapping[str, dict],
                   loss_limit: Decimal) -> list[dict[str, Any]]:
    """Every open foreign-currency invoice of a company (the forecast's inputs, see engine.load_inputs), soonest
    first. `histories`: {currency: {day: PLN per unit}}; `owner_profits`: {document id: Money}."""
    company = inputs["company"]
    as_of = date.fromisoformat(company["as_of_date"])
    base, country = company["base_currency"], company.get("country", "PL")
    rates = {k: Decimal(v) for k, v in inputs["rates"].items()}
    items = [i for i in inputs["open_items"] if i["kind"] in ("receivable", "payable")]
    held = balances(inputs["accounts"], inputs["transactions"], as_of)
    margin = average_margin(inputs["transactions"], as_of)
    out = []
    for item in items:
        currency = item["amount"]["currency"]
        if currency == base or currency not in rates:
            continue
        found = assess(item, as_of=as_of, country=country, base=base, spot=rates[currency],
                       history=history_window(histories.get(currency, {}), as_of), open_items=items, held=held,
                       owner_profit=owner_profits.get(item["id"]), margin=margin, loss_limit=loss_limit)
        if found:
            out.append(found)
    return sorted(out, key=lambda a: (a["expected_cash_date"], a["document_id"]))
