"""Money helpers. Money is a decimal string plus currency, never a float."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("money must not be a float")
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc


def german_decimal(text: str) -> Decimal:
    return to_decimal(text.strip().replace(".", "").replace(",", "."))


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money(value, currency: str) -> dict:
    amount = round_cents(to_decimal(value))
    if amount == 0:
        amount = abs(amount)
    return {"amount": format(amount, "f"), "currency": currency}
