"""Money is a decimal string plus currency, never a float."""
from decimal import ROUND_HALF_UP, Decimal


def money(amount: Decimal | str | int, currency: str) -> dict[str, str]:
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"amount": format(value, "f"), "currency": currency}


def amount_of(m: dict | None) -> Decimal:
    return Decimal(m["amount"]) if m else Decimal(0)
