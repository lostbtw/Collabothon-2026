"""Generated text may only contain numbers from the tool results (format- and sign-insensitive)."""
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

# grouped thousands ("30,000", "1 299,00", "1,299.00") first, then plain numbers ("0.86", "11.5", "30000")
_NUMBER = re.compile(
    r"\d{1,3}(?:([,   ])\d{3})(?:\1\d{3})*(?:[.,]\d+)?(?!\d)"
    r"|\d+(?:[.,]\d+)?"
)


def _value(token: str, group_sep: str | None) -> Decimal | None:
    if group_sep:
        token = token.replace(group_sep, "")
    token = token.replace(",", ".")
    try:
        return abs(Decimal(token)).normalize()
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    found = set()
    for m in _NUMBER.finditer(text):
        value = _value(m.group(0), m.group(1))
        if value is not None:
            found.add(value)
    return found


def numbers_of(results: Any) -> set[Decimal]:
    return numbers_in(json.dumps(results, ensure_ascii=False))


def unexpected_numbers(texts: list[str], tool_results: Any) -> list[Decimal]:
    allowed = numbers_of(tool_results)
    seen: set[Decimal] = set()
    for text in texts:
        seen |= numbers_in(text)
    return sorted(seen - allowed)
