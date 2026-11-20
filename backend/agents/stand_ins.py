"""Stand-ins for role 4's liquidity numbers until #44 (4.3) lands as backend/finance/engine.py.

Every number here is from the role 4 spec (#4) or the illustrative price lists named in spec #5; none is made up
by a model. When the engine exists, backend.agents.tools calls it instead.
"""
from decimal import ROUND_CEILING, Decimal

# Stress case per company: role 4 spec, "Stress: Nordwind pays 21 Dec ... about -28,170".
STRESS = {
    "co_borsuk": {"label": "Nordwind pays 21 Dec", "date": "2026-12-21", "balance": {"amount": "-28170.00", "currency": "PLN"}},
}

# Illustrative price lists of the simulated bank (spec #5: product names; pricing illustrative, not an offer).
PRICE_LISTS = {
    "co_borsuk": {"bank": "Sandbox Bank", "product": "mBank kredyt w rachunku bieżącym (illustrative)",
                  "interest_rate_pct": "11.5", "arrangement_fee_pct_of_limit": "1", "min_limit": None,
                  "note": "Illustrative price list of the simulated bank, not an offer"},
    "co_amalfi": {"bank": "Sandbox Bank", "product": "Commerzbank Gewerbekredit (illustrative)",
                  "interest_rate_pct": "11.5", "arrangement_fee_pct_of_limit": "1",
                  "min_limit": {"amount": "5000.00", "currency": "EUR"},
                  "note": "Illustrative price list of the simulated bank, not an offer"},
}

SIZING_STEP = Decimal("5000")


def size_credit_line(shortfall: Decimal, min_limit: Decimal | None = None) -> Decimal:
    """Role 4's sizing rule: the stress shortfall rounded up to the next 5,000 (30,000 for Borsuk Labs)."""
    limit = (shortfall / SIZING_STEP).to_integral_value(rounding=ROUND_CEILING) * SIZING_STEP
    return max(limit, min_limit or Decimal(0))
