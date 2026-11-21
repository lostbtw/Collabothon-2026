"""Polish tax payments (VAT, CIT advance, PIT-4, ZUS) as forecast components; an open month is estimated from closed ones."""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from . import settings
from .calendar import add_months, day_in_month, last_day_of_month, on_or_after

CENT = Decimal("0.01")
UNIT = Decimal("1")
ZERO = Decimal(0)
MAX_DOCUMENT_LINKS = 5

RULES = {
    "vat": ("PL-TAX-VAT", "VAT (JPK_V7M): output VAT minus deductible input VAT, due on the 25th of the next month"),
    "cit": ("PL-TAX-CIT", "CIT advance: 9% of profit since 1 January minus earlier advances, due on the 20th of the next month"),
    "pit4": ("PL-TAX-PIT4", "PIT-4: income tax withheld from salaries, due on the 20th of the next month"),
    "zus": ("PL-TAX-ZUS", "ZUS: social and health contributions for salaries, due on the 15th of the next month"),
}


def money(value: Decimal, currency: str) -> dict[str, str]:
    return {"amount": f"{Decimal(value).quantize(CENT, ROUND_HALF_UP):.2f}", "currency": currency}


def _whole(value: Decimal) -> Decimal:
    return Decimal(value).quantize(UNIT, ROUND_HALF_UP)


def _shown(value: Decimal) -> str:
    return f"{Decimal(value):,.2f}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pln_unit(base: str, rates: dict[str, Decimal]) -> Decimal:
    if base == "PLN":
        return Decimal(1)
    if "PLN" in rates:
        return Decimal(rates["PLN"])
    return Decimal(1) / settings.DEMO_DAY_RATES_PLN[base]


def due_date(day_of_month: int, year: int, month: int) -> date:
    y, m = add_months(year, month, 1)
    return on_or_after(day_in_month(y, m, day_of_month), "PL")


def gross_from_net(net: Decimal, p: Decimal = Decimal(1)) -> Decimal:
    net = Decimal(net)
    keep = 1 - settings.ZUS_EMPLOYEE
    factor = keep * (1 - settings.HEALTH_RATE - settings.PIT_RATE)
    fixed = (settings.PIT_RATE * settings.PIT_COSTS_PLN + settings.PIT_REDUCTION_PLN) * p
    gross = (net - fixed) / factor
    if settings.PIT_RATE * (gross * keep - settings.PIT_COSTS_PLN * p) - settings.PIT_REDUCTION_PLN * p < 0:
        gross = net / (keep * (1 - settings.HEALTH_RATE))
    return gross.quantize(CENT, ROUND_HALF_UP)


def pit4_advance(gross: Decimal, ytd_base_before: Decimal, p: Decimal = Decimal(1)) -> tuple[Decimal, Decimal]:
    base = _whole(Decimal(gross) * (1 - settings.ZUS_EMPLOYEE) - settings.PIT_COSTS_PLN * p)
    threshold = settings.PIT_THRESHOLD_PLN * p
    high = min(base, max(ZERO, Decimal(ytd_base_before) + base - threshold))
    low = base - high
    tax = settings.PIT_RATE * low + settings.PIT_RATE_HIGH * high
    advance = max(ZERO, _whole(tax - settings.PIT_REDUCTION_PLN * p))
    return advance, base


def zus_payment(gross: Decimal) -> Decimal:
    gross = Decimal(gross)
    total = gross * (settings.ZUS_EMPLOYER + settings.ZUS_EMPLOYEE) + settings.HEALTH_RATE * gross * (1 - settings.ZUS_EMPLOYEE)
    return total.quantize(CENT, ROUND_HALF_UP)


def tax_document(doc: dict) -> dict | None:
    if doc.get("status") in ("duplicate", "rejected"):
        return None
    day = doc.get("sale_date") or doc.get("issue_date")
    totals = doc.get("totals") or {}
    net = totals.get("net")
    if not day or not net:
        return None
    flags = doc.get("flags") or []
    deductible = not (doc.get("doc_type") == "receipt" or "vat_not_deductible" in flags or "buyer_not_company" in flags)
    return {
        "id": doc["id"],
        "direction": doc.get("direction"),
        "month": str(day)[:7],
        "label": doc.get("number") or doc["id"],
        "net": net,
        "vat": totals.get("vat") or None,
        "deductible": deductible,
    }


def _month_key(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, ZERO) / len(values) if values else ZERO


def _link(kind: str, id_: str, label: str, url: str | None = None) -> dict[str, str]:
    out = {"kind": kind, "id": id_, "label": label}
    if url:
        out["url"] = url
    return out


def _evidence(tax: str, docs: list[tuple[Decimal, dict]], salaries: list[dict] | None = None) -> list[dict]:
    rule_id, rule_label = RULES[tax]
    out = [_link("rule", rule_id, rule_label)]
    ranked = sorted(docs, key=lambda x: (-x[0], x[1]["id"]))[:MAX_DOCUMENT_LINKS]
    out += [_link("document", d["id"], d["label"], f"/documents/{d['id']}") for _, d in ranked]
    out += [s["evidence"] for s in (salaries or []) if s.get("evidence")][:MAX_DOCUMENT_LINKS]
    return out


EXPLAINERS = {
    "vat": "VAT you charged clients minus VAT you paid suppliers",
    "cit": f"Monthly advance on company income tax: {settings.CIT_RATE * 100:.0f} % of this year's profit, "
           "minus the advances already due",
    "pit4": "Income tax held back from salaries and passed on to the tax office",
    "zus": "Social and health insurance for the people on the payroll",
}


def _step(label: str, op: str, amount: Decimal | None = None, base: str = "PLN") -> dict:
    return {"label": label, "op": op, "amount": None if amount is None else money(amount, base)}


def _to_pay(amount: Decimal, base: str) -> dict:
    return _step("To pay, rounded to whole złoty" if base == "PLN" else "To pay, rounded", "equals", amount, base)


def _pct(rate: Decimal) -> str:
    return f"{rate * 100:.2f}".rstrip("0").rstrip(".") + " %"


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _month_names(months: list[tuple[int, int]]) -> str:
    names = [calendar.month_abbr[m] for _, m in months]
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)


def _component(tax: str, y: int, m: int, due: date, amount: Decimal, base: str, schedule: str, estimate: bool,
               evidence: list[dict], breakdown: list[dict], *, confidence: float | None = None) -> dict:
    period = f"{calendar.month_name[m]} {y}"
    label = {
        "vat": f"VAT for {period}",
        "cit": f"CIT advance for {period}",
        "pit4": f"PIT-4 for {period}",
        "zus": f"ZUS for {period}",
    }[tax]
    if estimate:
        label += " (estimate)"
    return {
        "id": f"c_tax_{tax}_{y}{m:02d}",
        "label": label,
        "kind": "social_security" if tax == "zus" else "tax",
        "amount_base": money(-amount, base),
        "schedule": schedule,
        "dates": [due.isoformat()],
        "confidence": confidence if confidence is not None else (
            settings.TAX_ESTIMATE_CONFIDENCE if estimate else settings.TAX_CONFIDENCE),
        "evidence": evidence,
        "explainer": EXPLAINERS[tax],
        "breakdown": breakdown,
    }


def tax_components(*, as_of: date, end: date, base: str, rates: dict[str, Decimal],
                   documents: list[dict], salaries: list[dict]) -> list[dict]:
    p = pln_unit(base, rates)

    output_vat: dict[str, Decimal] = defaultdict(Decimal)
    input_vat: dict[str, Decimal] = defaultdict(Decimal)
    lost_vat: dict[str, Decimal] = defaultdict(Decimal)
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    purchase_net: dict[str, Decimal] = defaultdict(Decimal)
    sales_with_vat: dict[str, int] = defaultdict(int)
    purchases_with_vat: dict[str, int] = defaultdict(int)
    month_docs: dict[str, list[tuple[Decimal, Decimal, dict]]] = defaultdict(list)

    for doc in documents:
        net_money = doc["net"]
        if net_money["currency"] not in rates:
            continue
        net = Decimal(net_money["amount"]) * rates[net_money["currency"]]
        vat_money = doc.get("vat")
        vat = ZERO
        if vat_money and vat_money["currency"] == "PLN":
            vat = Decimal(vat_money["amount"]) * p
        month = doc["month"]
        if doc["direction"] == "sale":
            revenue[month] += net
            output_vat[month] += vat
            sales_with_vat[month] += vat > 0
        elif doc["direction"] == "purchase":
            purchase_net[month] += net
            if doc["deductible"]:
                input_vat[month] += vat
                purchases_with_vat[month] += vat > 0
            else:
                lost_vat[month] += vat
        else:
            continue
        month_docs[month].append((net, vat, doc))

    paid: dict[str, list[dict]] = defaultdict(list)
    for s in salaries:
        if Decimal(s["net"]) > 0:
            paid[_month_key(s["day"].year, s["day"].month)].append(
                {**s, "gross": gross_from_net(Decimal(s["net"]), p)})
    gross_sum: dict[str, Decimal] = {}
    pit_sum: dict[str, Decimal] = {}
    zus_sum: dict[str, Decimal] = {}
    net_sum: dict[str, Decimal] = {}
    base_sum: dict[str, Decimal] = {}
    employer_sum: dict[str, Decimal] = {}
    employee_sum: dict[str, Decimal] = {}
    health_sum: dict[str, Decimal] = {}
    pit_raw_sum: dict[str, Decimal] = {}
    ytd_base: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for month in sorted(paid):
        year = month[:4]
        gross_sum[month] = pit_sum[month] = zus_sum[month] = ZERO
        net_sum[month] = base_sum[month] = employer_sum[month] = employee_sum[month] = ZERO
        health_sum[month] = pit_raw_sum[month] = ZERO
        for s in paid[month]:
            before = ytd_base[(year, s["key"])]
            advance, pit_base = pit4_advance(s["gross"], before, p)
            ytd_base[(year, s["key"])] += pit_base
            high = min(pit_base, max(ZERO, before + pit_base - settings.PIT_THRESHOLD_PLN * p))
            employer = (s["gross"] * settings.ZUS_EMPLOYER).quantize(CENT, ROUND_HALF_UP)
            employee = (s["gross"] * settings.ZUS_EMPLOYEE).quantize(CENT, ROUND_HALF_UP)
            zus = zus_payment(s["gross"])
            net_sum[month] += Decimal(s["net"])
            gross_sum[month] += s["gross"]
            base_sum[month] += pit_base
            pit_sum[month] += advance
            pit_raw_sum[month] += settings.PIT_RATE * (pit_base - high) + settings.PIT_RATE_HIGH * high
            zus_sum[month] += zus
            employer_sum[month] += employer
            employee_sum[month] += employee
            health_sum[month] += zus - employer - employee

    keys = set(month_docs) | set(paid)
    if not keys:
        return []
    first_y, first_m = map(int, min(keys).split("-"))
    months: list[tuple[int, int]] = []
    y, m = first_y, first_m
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = add_months(y, m, 1)

    closed = [(y, m) for y, m in months if last_day_of_month(y, m) < as_of]
    recent = closed[-settings.TAX_ESTIMATE_MONTHS:]
    n_recent = settings.TAX_ESTIMATE_MONTHS

    def position(month: str) -> Decimal:
        return output_vat[month] - input_vat[month]

    def profit(month: str) -> Decimal:
        gross = gross_sum.get(month, ZERO)
        return (revenue[month] - purchase_net[month] - lost_vat[month] - gross
                - gross * settings.ZUS_EMPLOYER)

    est_position = _mean([position(_month_key(*c)) for c in recent])
    est_profit = _mean([profit(_month_key(*c)) for c in recent])
    estimate_note = f"mean of the last {n_recent} closed months"
    recent_names = _month_names(recent)
    recent_keys = [_month_key(*c) for c in recent]
    out: list[dict] = []

    def not_closed(m: int, what: str) -> dict:
        return _step(f"{calendar.month_name[m]} is not over yet: {what} is the average of {recent_names}", "note")

    def in_window(due: date) -> bool:
        return as_of < due <= end

    carry = ZERO
    for y, m in months:
        key = _month_key(y, m)
        is_closed = (y, m) in closed
        pos = position(key) if is_closed else est_position
        pay = pos - carry
        used_carry = carry
        if pay < 0:
            carry, pay = -pay, ZERO
        else:
            carry = ZERO
        due = due_date(settings.VAT_DUE_DAY, y, m)
        amount = _whole(pay)
        if amount > 0 and in_window(due):
            when = f"{_ordinal(settings.VAT_DUE_DAY)} of the next month, next business day if not (Ordynacja podatkowa art. 12 § 5): "
            if is_closed:
                schedule = (f"{when}output VAT {_shown(output_vat[key])} − deductible input VAT {_shown(input_vat[key])}"
                            + (f" − carried forward {_shown(used_carry)}" if used_carry else ""))
                docs = [(vat, d) for _, vat, d in month_docs[key] if vat > 0]
                steps = [_step(f"VAT on {_count(sales_with_vat[key], 'sales invoice')}", "start", output_vat[key], base),
                         _step(f"VAT on {_count(purchases_with_vat[key], 'purchase invoice')} you can deduct", "minus",
                               input_vat[key], base)]
            else:
                schedule = f"{when}output VAT − deductible input VAT, {estimate_note}" + (
                    f" − carried forward {_shown(used_carry)}" if used_carry else "")
                docs = [(vat, d) for k in recent_keys for _, vat, d in month_docs[k] if vat > 0]
                steps = [_step("VAT to pay in an average month", "start", est_position, base)]
            if used_carry:
                steps.append(_step("Overpaid VAT carried from earlier months", "minus", used_carry, base))
            steps.append(_to_pay(amount, base))
            if not is_closed:
                steps.append(not_closed(m, "the VAT"))
            out.append(_component("vat", y, m, due, amount, base, schedule, not is_closed, _evidence("vat", docs), steps))

    ytd = ZERO
    advances = ZERO
    for y, m in months:
        if m == 1:
            ytd = advances = ZERO
        key = _month_key(y, m)
        is_closed = (y, m) in closed
        month_profit = profit(key) if is_closed else est_profit
        ytd += month_profit
        due_amount = max(ZERO, _whole(settings.CIT_RATE * max(ytd, ZERO)) - advances)
        advances += due_amount
        due = due_date(settings.CIT_DUE_DAY, y, m)
        if due_amount > 0 and in_window(due):
            when = f"{_ordinal(settings.CIT_DUE_DAY)} of the next month, next business day if not (Ordynacja podatkowa art. 12 § 5): "
            schedule = (f"{when}{settings.CIT_RATE * 100:.0f}% × profit since 1 January {_shown(ytd)} − advances already due this year "
                        f"{_shown(advances - due_amount)}")
            if not is_closed:
                schedule += f"; month profit is the {estimate_note}"
            docs = [(net, d) for k in ([key] if is_closed else recent_keys) for net, _, d in month_docs[k]]
            steps = [_step("Profit since 1 January", "start", ytd, base),
                     _step(f"{settings.CIT_RATE * 100:.0f} % tax on that profit", "equals", settings.CIT_RATE * ytd, base)]
            if advances - due_amount:
                steps.append(_step("Advances already due this year", "minus", advances - due_amount, base))
            steps.append(_to_pay(due_amount, base))
            if not is_closed:
                steps.append(not_closed(m, "its profit"))
            out.append(_component("cit", y, m, due, due_amount, base, schedule, not is_closed, _evidence("cit", docs),
                                  steps))

    for month in sorted(paid):
        y, m = int(month[:4]), int(month[5:])
        people = len(paid[month])
        for tax, amount, due_day in (("pit4", pit_sum[month], settings.PIT4_DUE_DAY),
                                     ("zus", zus_sum[month], settings.ZUS_DUE_DAY)):
            due = due_date(due_day, y, m)
            if amount > 0 and in_window(due):
                schedule = (f"{_ordinal(due_day)} of the next month, next business day if not (Ordynacja podatkowa art. 12 § 5): "
                            f"{people} salaries, gross pay {_shown(gross_sum[month])} (inferred from net pay)")
                gross, employee, health = gross_sum[month], employee_sum[month], health_sum[month]
                rounding = gross - net_sum[month] - employee - health - pit_sum[month]
                steps = [_step(f"1. Gross pay: what the {_count(people, 'person', 'people')} earned before the "
                               "employer held back insurance and tax", "note"),
                         _step("Net pay, as paid from the bank", "start", net_sum[month], base),
                         _step(f"Employee social insurance held back, {_pct(settings.ZUS_EMPLOYEE)}", "plus",
                               employee, base),
                         _step(f"Health insurance held back, {_pct(settings.HEALTH_RATE)}", "plus", health, base),
                         _step("Income tax held back (PIT-4)", "plus", pit_sum[month], base)]
                if rounding:
                    steps.append(_step("Rounding of the tax to whole złoty", "plus" if rounding > 0 else "minus",
                                       abs(rounding), base))
                steps.append(_step("Gross pay", "equals", gross, base))
                if tax == "pit4":
                    reduction = pit_raw_sum[month] - amount
                    steps += [_step("2. Income tax: what the employer passes on to the tax office", "note"),
                              _step("Gross pay", "start", gross, base),
                              _step(f"Employee social insurance, {_pct(settings.ZUS_EMPLOYEE)}", "minus", employee, base),
                              _step(f"Work costs, {settings.PIT_COSTS_PLN:,.0f} PLN per person", "minus",
                                    settings.PIT_COSTS_PLN * p * people, base),
                              _step("Taxable income, rounded to whole złoty per person", "equals", base_sum[month], base),
                              _step(f"Tax: {_pct(settings.PIT_RATE)} of taxable income ({_pct(settings.PIT_RATE_HIGH)} "
                                    f"above {settings.PIT_THRESHOLD_PLN:,.0f} PLN a year)", "start", pit_raw_sum[month], base),
                              _step(f"Tax-free reduction, {settings.PIT_REDUCTION_PLN:,.0f} PLN per person, and rounding",
                                    "minus", reduction, base),
                              _step("PIT-4 to pay", "equals", amount, base)]
                else:
                    steps += [_step("2. ZUS: what goes to the social insurance office", "note"),
                              _step(f"Employer social insurance, {_pct(settings.ZUS_EMPLOYER)} of gross, paid on top",
                                    "start", employer_sum[month], base),
                              _step(f"Employee social insurance, {_pct(settings.ZUS_EMPLOYEE)}, held back from pay",
                                    "plus", employee, base),
                              _step(f"Health insurance, {_pct(settings.HEALTH_RATE)}, held back from pay", "plus",
                                    health, base),
                              _step("ZUS to pay", "equals", amount, base)]
                steps.append(_step("Net pay is what the bank shows; the rest is worked out with the standard "
                                   "employment contract rates", "note"))
                out.append(_component(tax, y, m, due, amount, base, schedule, False,
                                      _evidence(tax, [], paid[month]), steps))

    return sorted(out, key=lambda c: (c["dates"][0], c["id"]))
