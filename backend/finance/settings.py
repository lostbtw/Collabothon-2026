"""Rules of the finance engine's method, the same for every company; override each with ORDO_FINANCE_<NAME>."""
import os
from decimal import Decimal


def _get(name: str, default, cast=None):
    raw = os.environ.get(f"ORDO_FINANCE_{name}")
    if raw is None:
        return default
    return (cast or type(default))(raw)


HORIZON_DAYS = _get("HORIZON_DAYS", 45)
EVENT_TAIL_DAYS = _get("EVENT_TAIL_DAYS", 14)
VARIABLE_WEEKS = _get("VARIABLE_WEEKS", 8)
BAND = _get("BAND", Decimal("0.5"), Decimal)
BAND_Z = _get("BAND_Z", 1.645)
DEFAULT_PAYMENT_DAYS = _get("DEFAULT_PAYMENT_DAYS", 14)

MIN_OCCURRENCES = _get("MIN_OCCURRENCES", 2)
STABLE_CV = _get("STABLE_CV", 0.02)
LOOSE_CV = _get("LOOSE_CV", 0.15)
CLIENT_CV = _get("CLIENT_CV", 0.5)

BUFFER_SHARE = _get("BUFFER_SHARE", Decimal("0.10"), Decimal)
BUFFER_MONTHS = _get("BUFFER_MONTHS", 3)
BUFFER_ROUND = _get("BUFFER_ROUND", Decimal("1000"), Decimal)

LATE_CONFIDENCE = _get("LATE_CONFIDENCE", 0.9)
STRESS_EXTRA_DAYS = _get("STRESS_EXTRA_DAYS", 14)
SIZING_STEP = _get("SIZING_STEP", Decimal("5000"), Decimal)

DEMO_DAY_RATES_PLN = {"PLN": Decimal("1"), "EUR": Decimal("4.41"), "USD": Decimal("4.0613")}

# FX Shield: no threshold of "large" here, the model judges against the company's own figures. Prices are illustrative.
FX_HISTORY_DAYS = _get("FX_HISTORY_DAYS", 1095)
FX_MIN_HISTORY = _get("FX_MIN_HISTORY", 500)
FX_NET_WINDOW_DAYS = _get("FX_NET_WINDOW_DAYS", 15)
FX_NATURAL_SHARE = _get("FX_NATURAL_SHARE", Decimal("0.05"), Decimal)
FX_FORWARD_COST = _get("FX_FORWARD_COST", Decimal("0.003"), Decimal)
FX_OPTION_COST = _get("FX_OPTION_COST", Decimal("0.012"), Decimal)
FX_LATE_DAYS = _get("FX_LATE_DAYS", 3)
FX_LATE_HEDGE_RATIO = _get("FX_LATE_HEDGE_RATIO", Decimal("0.8"), Decimal)
FX_CONTEXT_MONTHS = _get("FX_CONTEXT_MONTHS", 12)

# Polish taxes for every company, as researched on 2026-11-21 (podatki.gov.pl, zus.pl); confirm with an accountant.
VAT_DUE_DAY = _get("VAT_DUE_DAY", 25)
CIT_DUE_DAY = _get("CIT_DUE_DAY", 20)
PIT4_DUE_DAY = _get("PIT4_DUE_DAY", 20)
ZUS_DUE_DAY = _get("ZUS_DUE_DAY", 15)
CIT_RATE = _get("CIT_RATE", Decimal("0.09"), Decimal)
PIT_RATE = _get("PIT_RATE", Decimal("0.12"), Decimal)
PIT_RATE_HIGH = _get("PIT_RATE_HIGH", Decimal("0.32"), Decimal)
PIT_THRESHOLD_PLN = _get("PIT_THRESHOLD_PLN", Decimal("120000"), Decimal)
PIT_COSTS_PLN = _get("PIT_COSTS_PLN", Decimal("250"), Decimal)
PIT_REDUCTION_PLN = _get("PIT_REDUCTION_PLN", Decimal("300"), Decimal)
ZUS_EMPLOYEE = _get("ZUS_EMPLOYEE", Decimal("0.1371"), Decimal)
ZUS_EMPLOYER = _get("ZUS_EMPLOYER", Decimal("0.2048"), Decimal)
HEALTH_RATE = _get("HEALTH_RATE", Decimal("0.09"), Decimal)
TAX_ESTIMATE_MONTHS = _get("TAX_ESTIMATE_MONTHS", 3)
TAX_CONFIDENCE = _get("TAX_CONFIDENCE", 0.9)
TAX_ESTIMATE_CONFIDENCE = _get("TAX_ESTIMATE_CONFIDENCE", 0.6)
