"""Rules of the finance engine's method: the same for every company, no company names, no story numbers.

Every value can be overridden with an environment variable `ORDO_FINANCE_<NAME>` (e.g. ORDO_FINANCE_HORIZON_DAYS=60).
Company-specific values (as-of date, balances, invoices, rates, buffer) always come from the data.
"""
import os
from decimal import Decimal


def _get(name: str, default, cast=None):
    raw = os.environ.get(f"ORDO_FINANCE_{name}")
    if raw is None:
        return default
    return (cast or type(default))(raw)


# Forecast
HORIZON_DAYS = _get("HORIZON_DAYS", 45)                  # default horizon (spec #4: 45-day forecast)
EVENT_TAIL_DAYS = _get("EVENT_TAIL_DAYS", 14)            # an owner event stays visible this long after it ends
VARIABLE_WEEKS = _get("VARIABLE_WEEKS", 8)               # everyday flows: weekday mean over these weeks (spike 03)
BAND = _get("BAND", Decimal("0.5"), Decimal)             # fallback band (short history): spending x(1+BAND), income x(1-BAND)
BAND_Z = _get("BAND_Z", 1.645)                           # band = +/- BAND_Z x weekly sd x open weeks (errors add up)
DEFAULT_PAYMENT_DAYS = _get("DEFAULT_PAYMENT_DAYS", 14)  # invoice without a due date: due this many days after issue

# Recurring series
MIN_OCCURRENCES = _get("MIN_OCCURRENCES", 2)
STABLE_CV = _get("STABLE_CV", 0.02)                      # amount varies <= 2%: confidence 0.95
LOOSE_CV = _get("LOOSE_CV", 0.15)                        # <= 15% (taxes, card rates): confidence 0.8
CLIENT_CV = _get("CLIENT_CV", 0.5)                       # clients paid by invoice: only the date must be regular

# Safety buffer: a share of the average monthly outflows of the last full months (rounded up)
BUFFER_SHARE = _get("BUFFER_SHARE", Decimal("0.10"), Decimal)
BUFFER_MONTHS = _get("BUFFER_MONTHS", 3)
BUFFER_ROUND = _get("BUFFER_ROUND", Decimal("1000"), Decimal)

# Stress case and credit-line sizing (#44)
LATE_CONFIDENCE = _get("LATE_CONFIDENCE", 0.9)           # a receivable below this confidence comes from a late payer
STRESS_EXTRA_DAYS = _get("STRESS_EXTRA_DAYS", 14)        # stress: the largest late receivable comes this much later
SIZING_STEP = _get("SIZING_STEP", Decimal("5000"), Decimal)  # credit line: the worst shortfall rounded up to this

# Exchange rates: the stored NBP table A rate (role 2's connector). Only while no table is stored, the demo-day
# rate of spec #4 is used ("4.41 PLN per EUR and 4.0613 PLN per USD, used everywhere").
DEMO_DAY_RATES_PLN = {"PLN": Decimal("1"), "EUR": Decimal("4.41"), "USD": Decimal("4.0613")}

# FX Shield (#47, spec #4): the method's parameters only. There is no threshold of "large" here: the model judges that
# against the company's own figures. Prices are illustrative placeholders, not an offer.
FX_HISTORY_DAYS = _get("FX_HISTORY_DAYS", 1095)                      # 3 years of NBP rates before the as-of date
FX_MIN_HISTORY = _get("FX_MIN_HISTORY", 500)                         # fewer stored rates: use the committed 3-year file
FX_NET_WINDOW_DAYS = _get("FX_NET_WINDOW_DAYS", 15)                  # opposite invoices this close in time offset each other
FX_NATURAL_SHARE = _get("FX_NATURAL_SHARE", Decimal("0.05"), Decimal)      # net exposure under this share: naturally hedged
FX_FORWARD_COST = _get("FX_FORWARD_COST", Decimal("0.003"), Decimal)       # illustrative forward margin, share of value
FX_OPTION_COST = _get("FX_OPTION_COST", Decimal("0.012"), Decimal)         # illustrative option premium, share of value
FX_LATE_DAYS = _get("FX_LATE_DAYS", 3)                               # a client this many days late on average is late
FX_LATE_HEDGE_RATIO = _get("FX_LATE_HEDGE_RATIO", Decimal("0.8"), Decimal) # share hedged for a late client (spec)
FX_CONTEXT_MONTHS = _get("FX_CONTEXT_MONTHS", 12)                    # full months of money in and out shown to the model
