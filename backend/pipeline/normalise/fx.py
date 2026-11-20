"""PL-FX-01: a foreign-currency document is converted at the NBP table-A mid rate of the last business day
before its issue date. "Business day" = a day NBP published a table, so weekends and holidays are skipped
by looking back to the latest published date.

`rates` is any callable `(currency, date) -> (rate: Decimal, table_no: str | None) | None` returning the rate
published on exactly that date, or None if no table was published. The real one is role 2's NBP connector
(#34, `/fx/rates`); `StandInRates` covers tests and demos until it lands.
"""
from datetime import date, timedelta
from decimal import Decimal

from .money import money, round_cents, to_decimal

BASE_CURRENCY = "PLN"
MAX_LOOKBACK_DAYS = 10


class RateNotFound(LookupError):
    pass


class StandInRates:
    """STAND-IN for the NBP rates connector (#34). Values are illustrative, not real NBP rates."""

    def __init__(self, table: dict | None = None):
        # {(currency, "YYYY-MM-DD"): ("rate", "table no or None")}
        self.table = table if table is not None else {
            ("USD", "2026-11-18"): ("3.9099", None),  # contracts/fixtures/document.json doc_pixel11
            ("EUR", "2026-11-18"): ("4.2310", None),
        }

    def __call__(self, currency: str, day: date):
        hit = self.table.get((currency, day.isoformat()))
        return (to_decimal(hit[0]), hit[1]) if hit else None


def pl_tax_rate(currency: str, issue_date: str, rates) -> dict:
    """FxConversion (common.schema.json) for PL-FX-01, or RateNotFound."""
    day = date.fromisoformat(issue_date)
    for back in range(1, MAX_LOOKBACK_DAYS + 1):
        candidate = day - timedelta(days=back)
        found = rates(currency, candidate)
        if found:
            rate, table_no = found
            return {
                "rate": format(to_decimal(rate), "f"),
                "rate_date": candidate.isoformat(),
                "source": f"NBP table A {table_no}" if table_no else "NBP table A (illustrative)",
                "rule": "pl_tax_prev_business_day",
            }
    raise RateNotFound(f"no {currency} rate in the {MAX_LOOKBACK_DAYS} days before {issue_date}")


def to_base(gross: dict, issue_date: str | None, rates, base_currency: str = BASE_CURRENCY):
    """(gross_base Money, fx FxConversion | None). Same currency: no conversion. Missing date or rate: (None, None)."""
    if gross["currency"] == base_currency:
        return money(gross["amount"], base_currency), None
    if not issue_date or rates is None:
        return None, None
    try:
        fx = pl_tax_rate(gross["currency"], issue_date, rates)
    except RateNotFound:
        return None, None
    return money(round_cents(to_decimal(gross["amount"]) * Decimal(fx["rate"])), base_currency), fx
