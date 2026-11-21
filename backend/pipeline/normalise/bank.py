"""Bank line (PSD2-shaped JSON in a RawItem) -> Transaction; the account-currency amount is the cash truth."""
import re
from decimal import ROUND_HALF_UP, Decimal

from .money import money, round_cents, to_decimal


class NormaliseError(ValueError):
    """The RawItem cannot become a Transaction; the caller marks it `failed` with this message."""


# "(4166.67 CHF @ 1.050 EUR/CHF)": 1 CHF = 1.050 EUR
RATE_IN_REFERENCE = re.compile(
    r"\(\s*(?P<foreign_amount>\d+(?:\.\d+)?)\s*(?P<foreign>[A-Z]{3})\s*@\s*(?P<rate>\d+(?:\.\d+)?)"
    r"\s*(?P<base>[A-Z]{3})\s*/\s*(?P<quote>[A-Z]{3})\s*\)"
)
# "... 45.00 USD KARTA *4417"
FOREIGN_AMOUNT = re.compile(r"(?<![\d.,])(?P<amount>\d+(?:[.,]\d{1,2})?)\s+(?P<currency>[A-Z]{3})\b")
CARD_LAST4 = re.compile(r"\*\s?(\d{4})\b")
ISO_CURRENCIES = {
    "PLN", "EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "CZK", "HUF", "JPY", "CAD", "AUD", "CNY",
}

_TYPE_BY_CODE = {
    "CARD_PAYMENT": "card_payment",
    "GIRO_CARD_PAYMENT": "card_payment",
    "CARD_SETTLEMENT": "card_settlement",
    "CARD_SETTLEMENT_DEBIT": "card_settlement",
    "CREDIT_CARD_PAYOUT": "card_settlement",
    "SALARY": "salary",
    "SALARY_PAYMENT": "salary",
    "TAX": "tax",
    "TAX_OFFICE_TRANSFER": "tax",
    "DIRECT_DEBIT": "direct_debit",
    "SEPA_DIRECT_DEBIT": "direct_debit",
    "FEE": "fee",
    "BANK_FEE": "fee",
    "FX": "fx",
    "INTERNAL": "internal",
    "INTERNAL_TRANSFER": "internal",
}
_TRANSFER_CODES = {
    "TRANSFER", "SEPA_CREDIT_TRANSFER", "SUPPLIER_PAYMENT", "RENT_PAYMENT", "INTERNATIONAL_WIRE_TRANSFER",
    "TRANSFER_OUT", "TRANSFER_IN",
}
_TAX_WORDS = ("tax office", "finanzamt", "urząd skarbowy", "urzad skarbowy", "stadtkasse", "tax prepayment")
_SOCIAL_WORDS = ("krankenkasse", "social", "zus", "sozialversicherung")


def _code(value) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def transaction_type(code: str, amount: Decimal, text: str) -> str:
    """Map the bank's proprietary code to the contract enum, refining direct debits by payee."""
    code = _code(code)
    lowered = text.lower()
    kind = _TYPE_BY_CODE.get(code)
    if kind is None:
        kind = ("transfer_out" if amount < 0 else "transfer_in") if code in _TRANSFER_CODES or not code else "other"
    if kind in ("direct_debit", "transfer_out", "other"):
        if any(w in lowered for w in _TAX_WORDS):
            return "tax"
        if any(w in lowered for w in _SOCIAL_WORDS):
            return "social_security"
    return kind


def transaction_id(account_id: str, external_id: str) -> str:
    """Deterministic id, so normalising the same bank line twice gives the same Transaction."""
    account_part = account_id[4:] if account_id.startswith("acc_") else account_id
    return "txn_" + re.sub(r"[^A-Za-z0-9]+", "_", f"{account_part}_{external_id}").strip("_")


def _iban(party) -> str | None:
    if isinstance(party, dict):
        return party.get("iban") or party.get("bban")
    return party or None


def normalise_bank_line(raw_item: dict, account: dict) -> dict:
    """Turn one `bank_transaction` RawItem into a contract Transaction; `account` needs `id` and `currency`."""
    line = raw_item.get("payload") or {}
    for field in ("entryReference", "bookingDate", "transactionAmount"):
        if not line.get(field):
            raise NormaliseError(f"bank line {raw_item.get('id')} has no {field}")

    account_ccy = account["currency"]
    stated = line["transactionAmount"]
    amount = to_decimal(stated["amount"])
    line_ccy = stated["currency"]
    description = line.get("remittanceInformationUnstructured") or ""
    outgoing = amount < 0
    name = (line.get("creditorName") if outgoing else line.get("debtorName")) or line.get("creditorName") \
        or line.get("debtorName")
    iban = _iban(line.get("creditorAccount") if outgoing else line.get("debtorAccount")) \
        or _iban(line.get("creditorAccount")) or _iban(line.get("debtorAccount"))
    value_date = line.get("valueDate") or None
    rate_date = value_date or line["bookingDate"]

    fx = None
    original_amount = None
    data_quality: list[str] = []

    if line_ccy == account_ccy:
        amount_base = amount
        foreign = _foreign_amount_in_text(description, account_ccy)
        if foreign is not None:
            foreign_amount, foreign_ccy = foreign
            original_amount = money(-foreign_amount if outgoing else foreign_amount, foreign_ccy)
            implied = (abs(amount) / foreign_amount).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            fx = {
                "rate": format(implied, "f"),
                "rate_date": rate_date,
                "source": f"bank card rate (implied: {format(abs(amount), 'f')} / {format(foreign_amount, 'f')})",
                "rule": "bank_actual",
            }
    else:
        # DQ-01: the statement booked a foreign amount on this account; the rate is in the reference text.
        match = RATE_IN_REFERENCE.search(description)
        if not match or match["base"] != account_ccy or match["quote"] != line_ccy or match["foreign"] != line_ccy:
            raise NormaliseError(
                f"bank line {raw_item.get('id')}: {line_ccy} amount on a {account_ccy} account and no "
                f"'(<amount> {line_ccy} @ <rate> {account_ccy}/{line_ccy})' in the reference"
            )
        if to_decimal(match["foreign_amount"]) != abs(amount):
            raise NormaliseError(
                f"bank line {raw_item.get('id')}: reference says {match['foreign_amount']} {line_ccy}, "
                f"line says {abs(amount)}"
            )
        rate = to_decimal(match["rate"])
        amount_base = round_cents(amount * rate)
        original_amount = money(amount, line_ccy)
        fx = {
            "rate": match["rate"],
            "rate_date": line["bookingDate"],
            "source": f"payment reference text '{match.group(0)}'",
            "rule": "statement_reference",
        }
        data_quality = ["currency_mismatch_fixed", "rate_from_reference_text"]

    card = line.get("cardLast4")
    if not card:
        found = CARD_LAST4.search(description)
        card = found.group(1) if found else None

    balance = (line.get("balanceAfterTransaction") or {}).get("balanceAmount")

    return {
        "id": transaction_id(account["id"], line["entryReference"]),
        "account_id": account["id"],
        "source_id": raw_item["source_id"],
        "raw_item_id": raw_item["id"],
        "external_id": line["entryReference"],
        "booking_date": line["bookingDate"],
        "value_date": value_date,
        "amount": money(amount, line_ccy),
        "amount_base": money(amount_base, account_ccy),
        "fx": fx,
        "original_amount": original_amount,
        "counterparty_name_raw": name or None,
        "counterparty_account": iban,
        "counterparty_id": None,  # resolved later by counterparty.py
        "description": description,
        "transaction_type": transaction_type(
            line.get("proprietaryBankTransactionCode"), amount, f"{name or ''} {description}"
        ),
        "card_last4": card,
        "balance_after": money(balance["amount"], balance["currency"]) if balance else None,
        "status": "booked",
        "category": None,  # set later by counterparty.py
        "recurring_series_id": None,  # set by the finance engine
        "match_status": "unmatched",
        "data_quality": data_quality,
    }


def _foreign_amount_in_text(text: str, account_ccy: str):
    """Find "45.00 USD" in a card line's text when the currency is not the account currency."""
    for m in FOREIGN_AMOUNT.finditer(text):
        ccy = m["currency"]
        if ccy in ISO_CURRENCIES and ccy != account_ccy:
            value = to_decimal(m["amount"].replace(",", "."))
            if value > 0:
                return value, ccy
    return None


def transaction_ingested_payload(txn: dict) -> dict:
    """Small payload for the `transaction.ingested` event (contracts/events.md). Amount is in account currency."""
    return {
        "transaction_id": txn["id"],
        "account_id": txn["account_id"],
        "amount": txn["amount_base"],
        "booking_date": txn["booking_date"],
    }
