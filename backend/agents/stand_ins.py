"""Fallback liquidity numbers when the finance engine is absent; never from a model."""
from decimal import ROUND_CEILING, Decimal

STRESS = {
    "co_borsuk": {"label": "Nordwind pays 21 Dec", "date": "2026-12-21", "balance": {"amount": "-28170.00", "currency": "PLN"}},
}

PRICE_LISTS = {
    "co_borsuk": {"bank": "Commerzbank", "product": "Commerzbank Kontokorrentkredit (illustrative)",
                  "interest_rate_pct": "11.5", "arrangement_fee_pct_of_limit": "1", "min_limit": None,
                  "note": "Illustrative price list of the simulated bank, not an offer"},
    "co_amalfi": {"bank": "Commerzbank", "product": "Commerzbank Gewerbekredit (illustrative)",
                  "interest_rate_pct": "11.5", "arrangement_fee_pct_of_limit": "1",
                  "min_limit": {"amount": "5000.00", "currency": "EUR"},
                  "note": "Illustrative price list of the simulated bank, not an offer"},
}

SIZING_STEP = Decimal("5000")


def size_credit_line(shortfall: Decimal, min_limit: Decimal | None = None) -> Decimal:
    limit = (shortfall / SIZING_STEP).to_integral_value(rounding=ROUND_CEILING) * SIZING_STEP
    return max(limit, min_limit or Decimal(0))
