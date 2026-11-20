import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from .checks import BASE_CURRENCY, Reading, VatLine, assess, normalise_vat_rate

METHOD = "docling_llm"
MAX_LINES = 10
DOC_TYPES = {"invoice", "simplified_invoice", "receipt", "proforma", "credit_note", "other"}
PAYMENT_METHODS = {"card", "transfer", "cash", "direct_debit", "unknown"}
PAID_AT_COUNTER = {"card", "cash"}
COUNTER_DOCS = {"receipt", "simplified_invoice"}
UNREADABLE_SELLER = "(unreadable)"
NO_BUYER = "(none printed)"
CENT = Decimal("0.01")


def build_document(answer: dict[str, Any], *, model: str, today: date | None = None,
                   ocr_score: float | None = None, warnings: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    today = today or date.today()
    seller = answer.get("seller") or {}
    buyer = answer.get("buyer") or {}

    gross = _money(answer.get("gross"))
    vat = _money(answer.get("vat"))
    net = _money(answer.get("net"))
    field_confidence = _field_confidence(answer.get("field_confidence"))
    if net is None and gross is not None and vat is not None:
        net = _format(Decimal(gross) - Decimal(vat))
        derived = [field_confidence[k] for k in ("gross", "vat") if k in field_confidence]
        if derived:
            field_confidence["net"] = min(derived)

    vat_lines = _vat_lines(answer.get("vat_lines"))
    raw_currency = _text(answer.get("currency"))
    currency = raw_currency.upper() if raw_currency and re.fullmatch(r"[A-Za-z]{3}", raw_currency) else BASE_CURRENCY
    raw_issue_date = _text(answer.get("issue_date"))
    seller_tax_id = _text(seller.get("tax_id"))

    reading = Reading(gross=gross, net=net, vat=vat, currency=raw_currency, issue_date=raw_issue_date,
                      seller_tax_id=seller_tax_id,
                      vat_lines=tuple(VatLine(line["rate"], line["net"], line["vat"]) for line in vat_lines))
    assessment = assess(reading, self_report=_number(answer.get("confidence"), 0.0),
                        field_confidence=field_confidence, ocr_score=ocr_score, today=today)

    lines, line_warnings = _lines(answer.get("lines"))
    doc_type = answer.get("doc_type") if answer.get("doc_type") in DOC_TYPES else "other"
    issue_date = _date(raw_issue_date)
    buyer_tax_id = _text(buyer.get("tax_id"))

    totals = {
        "net": _amount(net, currency),
        "vat": _amount(vat, currency),
        "gross": _amount(gross or "0.00", currency),
        "gross_base": _amount(gross, currency) if currency == BASE_CURRENCY and gross is not None else None,
        "fx": None,
    }

    return {
        "doc_type": doc_type,
        "number": _text(answer.get("number")),
        "issue_date": issue_date,
        "sale_date": _date(_text(answer.get("sale_date"))),
        "due_date": _date(_text(answer.get("due_date"))),
        "seller": {
            "counterparty_id": None,
            "name": _text(seller.get("name")) or UNREADABLE_SELLER,
            "tax_id": seller_tax_id,
            "country": _country(seller.get("country")),
            "address": _text(seller.get("address")),
        },
        "buyer": {
            "counterparty_id": None,
            "name": _text(buyer.get("name")) or NO_BUYER,
            "tax_id": buyer_tax_id,
            "country": _country(buyer.get("country")),
            "address": _text(buyer.get("address")),
            "is_company": buyer_tax_id is not None,
        },
        "totals": totals,
        "vat_lines": vat_lines,
        "lines": lines,
        "payment": _payment(answer, doc_type, issue_date),
        "extraction": {
            "method": METHOD,
            "model": model,
            "confidence": assessment.confidence,
            "field_confidence": assessment.field_confidence,
            "warnings": [*warnings, *line_warnings, *assessment.warnings],
            "trace_id": None,
        },
        "category_suggestion": None,
        "status": assessment.status,
        "flags": assessment.flags,
    }


def _vat_lines(raw: Any) -> list[dict[str, str]]:
    result = []
    for line in raw or []:
        if not isinstance(line, dict):
            continue
        rate = normalise_vat_rate(_text(line.get("rate")))
        net, vat, gross = _money(line.get("net")), _money(line.get("vat")), _money(line.get("gross"))
        if net is None and gross is not None and vat is not None:
            net = _format(Decimal(gross) - Decimal(vat))
        if rate is None or net is None or vat is None:
            continue
        result.append({"rate": rate, "net": net, "vat": vat})
    return result


def _lines(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    items = [line for line in raw or [] if isinstance(line, dict) and _text(line.get("description"))]
    warnings = [f"Only the first {MAX_LINES} of {len(items)} lines were read"] if len(items) > MAX_LINES else []
    lines = [{
        "description": _text(line["description"]),
        "quantity": _quantity(line.get("quantity")),
        "unit_price": _money(line.get("unit_price")),
        "net": _money(line.get("net")),
        "vat_rate": normalise_vat_rate(_text(line.get("vat_rate"))),
    } for line in items[:MAX_LINES]]
    return lines, warnings


def _payment(answer: dict[str, Any], doc_type: str, issue_date: str | None) -> dict[str, Any]:
    method = answer.get("payment_method") if answer.get("payment_method") in PAYMENT_METHODS else "unknown"
    card = _text(answer.get("card_last4"))
    paid_at_counter = doc_type in COUNTER_DOCS and method in PAID_AT_COUNTER
    return {
        "method": method,
        "card_last4": card if card and re.fullmatch(r"\d{4}", card) else None,
        "paid": True if paid_at_counter else None,
        "paid_date": issue_date if paid_at_counter else None,
        "bank_account": _text(answer.get("bank_account")),
    }


def _field_confidence(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    return {key: max(0.0, min(1.0, float(value))) for key, value in raw.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)}


def _money(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return _format(number) if number.is_finite() else None


def _format(number: Decimal) -> str:
    return str(number.quantize(CENT, rounding=ROUND_HALF_UP))


def _amount(value: str | None, currency: str) -> dict[str, str] | None:
    return {"amount": value, "currency": currency} if value is not None else None


def _quantity(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _country(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text and re.fullmatch(r"[A-Za-z]{2}", text) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
