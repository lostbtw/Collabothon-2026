"""Formatting engine numbers into card text. Text never computes a number; it only prints one it was given."""
from datetime import date
from decimal import Decimal


def fmt_money(m: dict[str, str], cents: bool = True) -> str:
    """{"amount": "-1299.00", "currency": "PLN"} -> "1,299.00 PLN" (sign dropped: the sentence says the direction)."""
    value = abs(Decimal(m["amount"]))
    text = f"{value:,.2f}" if cents or value != value.to_integral_value() else f"{value:,.0f}"
    return f"{text} {m['currency']}"


def ordinal_day(d: date) -> str:
    n = d.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')}"
