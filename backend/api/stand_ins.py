"""Stand-ins for computations that live elsewhere; numbers from fixtures, never a model."""
from datetime import date, timedelta
from decimal import Decimal

DEMO_DAY_RATES_PLN = {"PLN": Decimal("1"), "EUR": Decimal("4.41"), "USD": Decimal("4.0613")}


def convert(amount: Decimal, currency: str, to: str) -> Decimal:
    pln = amount * DEMO_DAY_RATES_PLN[currency]
    return pln / DEMO_DAY_RATES_PLN[to]


def previous_business_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fx_rate(currency: str, on: date, rule: str) -> dict | None:
    if currency not in DEMO_DAY_RATES_PLN or currency == "PLN":
        return None
    rate_date = previous_business_day(on) if rule == "pl_tax_prev_business_day" else on
    return {
        "rate": str(DEMO_DAY_RATES_PLN[currency]),
        "rate_date": rate_date.isoformat(),
        "source": "Demo-day rate (stand-in until the NBP table is ingested)",
        "rule": rule,
    }


FX_EXPOSURE = {
    "co_borsuk": [
        {
            "document_id": "doc_fvlake01",
            "direction": "receivable",
            "amount": {"amount": "40000.00", "currency": "USD"},
            "value_today_base": {"amount": "162452.00", "currency": "PLN"},
            "expected_cash_date": "2027-01-05",
            "horizon_days": 45,
            "scenarios": 724,
            "bad_case_p95": {"amount": "-6374.00", "currency": "PLN"},
            "expected_shortfall": {"amount": "-6595.00", "currency": "PLN"},
            "deal_profit": {"amount": "8000.00", "currency": "PLN"},
            "profit_source": "owner",
            "verdict": "hedge_proposed",
            "recommendation_id": "rec_fx01",
        },
        {
            "document_id": "doc_fv1007",
            "direction": "receivable",
            "amount": {"amount": "18400.00", "currency": "EUR"},
            "value_today_base": {"amount": "81989.00", "currency": "PLN"},
            "horizon_days": 45,
            "expected_shortfall": {"amount": "-1426.00", "currency": "PLN"},
            "verdict": "not_worth_it",
            "recommendation_id": "rec_fx02",
        },
    ]
}
