"""Recurring series and weekday averages from booked bank lines (D-08, ported from spike 03). Pure, no database.

A *flow* is one booked bank line in the company's base currency. Flows are grouped by counterparty and by the
payment reference with its digits removed (the *template*), so one counterparty can carry several series: the
tax office's monthly wage tax, quarterly income tax and quarterly trade tax are three series, not one average.

A group is a recurring series when it occurs once per month (or once per quarter) without gaps, on a date rule
that fits every occurrence, with a stable amount:

    exact               the same day of the month
    on_or_after         that day, moved to the next business day on weekends and holidays (PL-CAL-04)
    after               the business day after that day (card payments booked one day after the purchase)
    last_business_day   the last business day of the month (pay run)

Everything else is *variable*: projected as the mean amount per weekday over the trailing 8 weeks.
"""
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, pstdev

from .calendar import add_months, day_in_month, last_business_day, next_business_day, on_or_after

VARIABLE_WEEKS = 8
MIN_OCCURRENCES = 2
STABLE_CV = 0.02       # amount varies by at most 2%: confidence 0.95
LOOSE_CV = 0.15        # by at most 15% (taxes, card rates): confidence 0.8, amount = mean
CLIENT_CV = 0.5        # clients paid by invoice: only the date must be regular
KINDS = {"salary": "salary", "tax": "tax", "social_security": "social_security"}


@dataclass
class Flow:
    day: date
    amount: Decimal               # base currency, negative = money out
    key: str                      # counterparty
    name: str                     # counterparty as shown
    template: str
    transaction: dict = field(repr=False)


@dataclass
class Series:
    id: str
    key: str
    label: str
    kind: str
    every: int                    # months: 1 or 3
    rule: str
    dom: int
    amount: Decimal
    confidence: float
    flows: list[Flow] = field(repr=False)

    def schedule(self) -> str:
        when = {"exact": f"on day {self.dom}", "on_or_after": f"on day {self.dom} or the next business day",
                "after": f"the business day after day {self.dom}",
                "last_business_day": "on the last business day"}[self.rule]
        period = "monthly" if self.every == 1 else "quarterly"
        return f"{period} {when} (seen {len(self.flows)}x)"

    def due_in(self, year: int, month: int, country: str) -> date:
        if self.rule == "last_business_day":
            return last_business_day(year, month, country)
        nominal = day_in_month(year, month, self.dom)
        if self.rule == "exact":
            return nominal
        if self.rule == "on_or_after":
            return on_or_after(nominal, country)
        return next_business_day(nominal, country)

    def dates(self, start: date, end: date, country: str) -> list[date]:
        """Projected dates in (start, end]."""
        last = self.flows[-1].day
        out, k = [], 1
        while True:
            y, m = add_months(last.year, last.month, k * self.every)
            due = self.due_in(y, m, country)
            if due > end:
                return out
            if due > start:
                out.append(due)
            k += 1


def template(text: str) -> str:
    """Payment reference without digits and extra spaces: 'PIT-4 10/2026 NIP 999...' -> 'PIT- / NIP'."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", text or "")).strip()


def counterparty_key(txn: dict) -> str:
    name = txn.get("counterparty_name_raw") or ""
    return txn.get("counterparty_id") or re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _fits(days: list[date], rule: str, dom: int, country: str) -> bool:
    probe = Series("", "", "", "", 1, rule, dom, Decimal(0), 0.0, [])
    return all(probe.due_in(d.year, d.month, country) == d for d in days)


def _date_rule(days: list[date], country: str) -> tuple[str, int] | None:
    doms = {d.day for d in days}
    if len(doms) == 1:
        return "exact", next(iter(doms))
    if _fits(days, "last_business_day", 0, country):
        return "last_business_day", 0
    for rule in ("on_or_after", "after"):
        for dom in range(1, 32):
            if _fits(days, rule, dom, country):
                return rule, dom
    return None


def _as_series(key: str, tmpl: str, flows: list[Flow], country: str, loose: bool = False) -> Series | None:
    if len(flows) < MIN_OCCURRENCES:
        return None
    months = [(f.day.year, f.day.month) for f in flows]
    if len(set(months)) != len(months):
        return None
    gaps = {(b[0] - a[0]) * 12 + b[1] - a[1] for a, b in zip(months, months[1:])}
    if gaps not in ({1}, {3}):
        return None
    rule = _date_rule([f.day for f in flows], country)
    if rule is None:
        return None
    amounts = [float(f.amount) for f in flows]
    avg = mean(amounts)
    if avg == 0 or (amounts[0] > 0) != (avg > 0):
        return None
    cv = pstdev(amounts) / abs(avg)
    if loose and cv > LOOSE_CV:  # a client paid by invoice: regular date, amount = mean of the last 3
        avg, cv = mean(amounts[-3:]), CLIENT_CV
    if cv > LOOSE_CV and not (loose and cv <= CLIENT_CV):
        return None
    types = [f.transaction.get("transaction_type") for f in flows]
    kind = KINDS.get(max(set(types), key=types.count), "fixed_recurring")
    sid = "ser_" + hashlib.sha1(f"{key}|{tmpl}".encode()).hexdigest()[:10]
    label = flows[-1].name or tmpl or key
    return Series(sid, key, label, kind, gaps.pop(), rule[0], rule[1], Decimal(str(round(avg, 2))),
                  0.95 if cv <= STABLE_CV else 0.8, flows)


def detect(flows: list[Flow], as_of: date, country: str,
           loose_keys: set[str] = frozenset()) -> tuple[list[Series], list[Flow]]:
    """Split flows booked up to `as_of` into recurring series and the rest (variable).

    `loose_keys`: counterparties whose amount may vary (clients paid by invoice); only their dates must be regular.
    A series whose next occurrence is long overdue (more than one period ago) has ended and is not projected.
    """
    groups: dict[tuple[str, str], list[Flow]] = defaultdict(list)
    for f in sorted(flows, key=lambda f: (f.day, f.transaction.get("id", ""))):
        if f.day <= as_of:
            groups[(f.key, f.template)].append(f)
    series, rest = [], []
    for (key, tmpl), group in groups.items():
        s = _as_series(key, tmpl, group, country, loose=key in loose_keys)
        if s is not None:
            y, m = add_months(s.flows[-1].day.year, s.flows[-1].day.month, s.every)
            if s.due_in(y, m, country) >= as_of - timedelta(days=31 * s.every):
                series.append(s)
                continue
        rest.extend(group)
    series.sort(key=lambda s: (s.kind, s.label, s.id))
    return series, rest


def weekday_averages(flows: list[Flow], as_of: date) -> dict[str, dict[int, Decimal]]:
    """Per counterparty: mean amount per weekday over the trailing 8 weeks (spike 03)."""
    cutoff = as_of - timedelta(weeks=VARIABLE_WEEKS)
    out: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for f in flows:
        if cutoff < f.day <= as_of:
            out[f.key][f.day.weekday()] += f.amount
    return {k: {wd: v / VARIABLE_WEEKS for wd, v in per.items()} for k, per in out.items()}
