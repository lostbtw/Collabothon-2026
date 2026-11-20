from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

REVIEW_BELOW = 0.75
PENALTY = 0.6
TOLERANCE = Decimal("0.02")
MAX_AGE_DAYS = 400
VAT_RATES = {"23", "8", "5", "0", "zw", "np", "oo"}
CURRENCIES = {"PLN", "EUR", "USD", "GBP", "CHF", "CZK"}
BASE_CURRENCY = "PLN"
NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
AMOUNT_FIELDS = ("gross", "net", "vat")


@dataclass(frozen=True)
class VatLine:
    rate: str | None
    net: str | None
    vat: str | None


@dataclass(frozen=True)
class Reading:
    gross: str | None = None
    net: str | None = None
    vat: str | None = None
    currency: str | None = None
    issue_date: str | None = None
    seller_tax_id: str | None = None
    vat_lines: tuple[VatLine, ...] = ()


@dataclass(frozen=True)
class Failure:
    check: str
    warning: str
    fields: tuple[str, ...]
    amount: bool = False


@dataclass(frozen=True)
class Assessment:
    confidence: float
    field_confidence: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    status: str = "extracted"
    flags: list[str] = field(default_factory=list)


def start_confidence(self_report: float, gross_confidence: float | None = None, ocr_score: float | None = None) -> float:
    candidates = [self_report]
    if gross_confidence is not None:
        candidates.append(gross_confidence)
    if ocr_score is not None:
        candidates.append(ocr_score)
    return _clamp(min(candidates))


def normalise_vat_rate(rate: str | None) -> str | None:
    if rate is None:
        return None
    text = str(rate).strip().lower().removesuffix("%").strip()
    if text.startswith("np"):
        return "np"
    try:
        number = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return text
    return str(int(number)) if number == number.to_integral_value() else format(number.normalize(), "f")


def nip_valid(tax_id: str | None) -> bool | None:
    digits = _polish_nip(tax_id)
    if digits is None:
        return None
    total = sum(int(d) * w for d, w in zip(digits, NIP_WEIGHTS)) % 11
    return total != 10 and total == int(digits[9])


def check_amounts(reading: Reading) -> list[Failure]:
    failures = []
    gross, net, vat = _amount(reading.gross), _amount(reading.net), _amount(reading.vat)
    if gross is not None and net is not None and vat is not None and abs(net + vat - gross) > TOLERANCE:
        failures.append(Failure("sum", f"Net {reading.net} plus VAT {reading.vat} does not equal gross {reading.gross}",
                                AMOUNT_FIELDS, amount=True))
    line_vats = [_amount(line.vat) for line in reading.vat_lines]
    if vat is not None and line_vats and None not in line_vats and abs(sum(line_vats) - vat) > TOLERANCE:
        failures.append(Failure("vat_lines", f"VAT lines add up to {sum(line_vats)}, the total VAT is {reading.vat}",
                                AMOUNT_FIELDS, amount=True))
    for line in reading.vat_lines:
        rate = normalise_vat_rate(line.rate)
        line_net, line_vat = _amount(line.net), _amount(line.vat)
        if rate is None or not rate.isdigit() or line_net is None or line_vat is None:
            continue
        if abs(line_net * Decimal(rate) / 100 - line_vat) > TOLERANCE:
            failures.append(Failure("vat_rate_math", f"VAT {line.vat} is not {rate}% of net {line.net}",
                                    AMOUNT_FIELDS, amount=True))
            break
    return failures


def check_nip(reading: Reading) -> list[Failure]:
    if nip_valid(reading.seller_tax_id) is False:
        return [Failure("nip", f"Seller tax id {reading.seller_tax_id} fails the NIP checksum", ("seller_tax_id",))]
    return []


def check_date(reading: Reading, today: date) -> list[Failure]:
    if not reading.issue_date:
        return [Failure("date", "No issue date found", ("issue_date",))]
    try:
        issued = date.fromisoformat(reading.issue_date)
    except ValueError:
        return [Failure("date", f"Issue date {reading.issue_date} is not a date", ("issue_date",))]
    if issued > today + timedelta(days=1):
        return [Failure("date", f"Issue date {reading.issue_date} is in the future", ("issue_date",))]
    if issued < today - timedelta(days=MAX_AGE_DAYS):
        return [Failure("date", f"Issue date {reading.issue_date} is more than {MAX_AGE_DAYS} days old", ("issue_date",))]
    return []


def check_vat_rates(reading: Reading) -> list[Failure]:
    odd = [line.rate for line in reading.vat_lines
           if line.rate is not None and normalise_vat_rate(line.rate) not in VAT_RATES]
    if odd:
        return [Failure("vat_rate", f"VAT rate {odd[0]} is not a Polish VAT rate", ("vat",))]
    return []


def check_currency(reading: Reading) -> list[Failure]:
    currency = _currency(reading.currency)
    if currency is None:
        return [Failure("currency", "No currency found", ())]
    if currency not in CURRENCIES:
        return [Failure("currency", f"Currency {reading.currency} is not recognised", ())]
    return []


def assess(reading: Reading, *, self_report: float, field_confidence: dict[str, float],
           ocr_score: float | None = None, today: date | None = None) -> Assessment:
    today = today or date.today()
    fields = {key: _clamp(value) for key, value in field_confidence.items()}
    warnings: list[str] = []
    flags: list[str] = []

    if _amount(reading.gross) is None:
        failures = [*check_nip(reading), *check_date(reading, today), *check_vat_rates(reading),
                    *check_currency(reading)]
        confidence = 0.0
        fields["gross"] = 0.0
        warnings.append("Gross amount not found")
        amount_failed = True
    else:
        failures = [*check_amounts(reading), *check_nip(reading), *check_date(reading, today),
                    *check_vat_rates(reading), *check_currency(reading)]
        confidence = start_confidence(self_report, fields.get("gross"), ocr_score)
        amount_failed = any(f.amount for f in failures)

    for failure in failures:
        confidence *= PENALTY
        warnings.append(failure.warning)
        for key in failure.fields:
            if key in fields:
                fields[key] *= PENALTY

    if not reading.seller_tax_id:
        warnings.append("No seller tax id found")

    confidence = round(confidence, 4)
    fields = {key: round(value, 4) for key, value in fields.items()}

    if confidence < REVIEW_BELOW:
        flags.append("low_confidence")
    if amount_failed:
        flags.append("amount_unclear")
    if not reading.seller_tax_id:
        flags.append("missing_tax_id")
    currency = _currency(reading.currency)
    if currency is not None and currency != BASE_CURRENCY:
        flags.append("foreign_currency")

    status = "needs_review" if confidence < REVIEW_BELOW or amount_failed else "extracted"
    return Assessment(confidence, fields, warnings, status, flags)


def _amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _currency(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip().upper()


def _polish_nip(tax_id: str | None) -> str | None:
    if not tax_id:
        return None
    text = str(tax_id).strip().upper().replace(" ", "").replace("-", "")
    text = text.removeprefix("PL")
    return text if len(text) == 10 and text.isdigit() else None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
