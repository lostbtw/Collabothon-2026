"""Money helpers. Money is a decimal string plus currency, never a float."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Parse a dot-decimal string ("-180.62") or a number into a Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("money must not be a float")
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc


def german_decimal(text: str) -> Decimal:
    """Parse German number format: "1.234,56" -> Decimal("1234.56")."""
    return to_decimal(text.strip().replace(".", "").replace(",", "."))


def round_cents(value: Decimal) -> Decimal:
    """Round to cents the way a bank books it (half up)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money(value, currency: str) -> dict:
    """Money object per common.schema.json#/$defs/Money."""
    amount = round_cents(to_decimal(value))
    if amount == 0:
        amount = abs(amount)  # never "-0.00"
    return {"amount": format(amount, "f"), "currency": currency}
