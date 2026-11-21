"""FA(3) e-invoice XML (KSeF) -> Document; parsed without a model, so confidence 1.0."""
import xml.etree.ElementTree as ET
from decimal import Decimal

from .fx import to_base
from .money import money, to_decimal

NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
_N = {"k": NS}

# P_13_x / P_14_x suffix -> rate label as written in P_12 on the lines
VAT_RATE_BY_FIELD = {"1": "23", "2": "8", "3": "5", "4": "4", "5": "oss", "6_1": "0", "6_2": "0 WDT",
                     "6_3": "0 EX", "7": "zw", "8": "np", "9": "np", "10": "oo", "11": "marza"}
DOC_TYPE = {"VAT": "invoice", "ZAL": "invoice", "ROZ": "invoice", "UPR": "simplified_invoice",
            "KOR": "credit_note", "KOR_ZAL": "credit_note", "KOR_ROZ": "credit_note"}
PAYMENT_METHOD = {"1": "cash", "2": "card", "6": "transfer"}


class Fa3Error(ValueError):
    pass


def _text(node, path):
    if node is None:
        return None
    value = node.findtext(path, namespaces=_N)
    return value.strip() if value and value.strip() else None


def _party(node):
    ident = node.find("k:DaneIdentyfikacyjne", _N) if node is not None else None
    address = node.find("k:Adres", _N) if node is not None else None
    lines = [_text(address, "k:AdresL1"), _text(address, "k:AdresL2")]
    return {
        "counterparty_id": None,  # resolved later by counterparty.py
        "name": _text(ident, "k:Nazwa") or "(no name)",
        "tax_id": _text(ident, "k:NIP"),
        "country": _text(address, "k:KodKraju"),
        "address": ", ".join(x for x in lines if x) or None,
    }


def parse_fa3(xml: bytes | str, raw_item: dict, company: dict, rates=None) -> dict:
    """`company` needs `id` and `tax_id` (bare NIP). `rates` see fx.py; needed only for foreign currency."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise Fa3Error(f"{raw_item.get('id')}: not XML ({exc})") from exc
    if root.tag != f"{{{NS}}}Faktura":
        raise Fa3Error(f"{raw_item.get('id')}: root is {root.tag}, expected FA(3) Faktura in {NS}")
    fa = root.find("k:Fa", _N)
    if fa is None or _text(fa, "k:P_15") is None:
        raise Fa3Error(f"{raw_item.get('id')}: no Fa/P_15 (gross total)")

    currency = _text(fa, "k:KodWaluty") or "PLN"
    seller = _party(root.find("k:Podmiot1", _N))
    buyer = _party(root.find("k:Podmiot2", _N))
    buyer["is_company"] = buyer["tax_id"] is not None
    own_nip = (company.get("tax_id") or "").removeprefix("PL")
    direction = "sale" if seller["tax_id"] == own_nip else "purchase"

    vat_lines, net_sum, vat_sum = [], Decimal(0), Decimal(0)
    for field, label in VAT_RATE_BY_FIELD.items():
        net, vat = _text(fa, f"k:P_13_{field}"), _text(fa, f"k:P_14_{field}")
        if net is None and vat is None:
            continue
        net_d, vat_d = to_decimal(net or "0"), to_decimal(vat or "0")
        net_sum, vat_sum = net_sum + net_d, vat_sum + vat_d
        vat_lines.append({"rate": label, "net": money(net_d, currency)["amount"], "vat": money(vat_d, currency)["amount"]})

    gross = money(_text(fa, "k:P_15"), currency)
    issue_date = _text(fa, "k:P_1")
    gross_base, fx = to_base(gross, issue_date, rates)

    lines = []
    for row in fa.findall("k:FaWiersz", _N):
        qty = _text(row, "k:P_8B")
        lines.append({
            "description": _text(row, "k:P_7") or "",
            "quantity": float(qty) if qty else None,  # schema type number; a count, not money
            "unit_price": _text(row, "k:P_9A") or _text(row, "k:P_9B"),
            "net": _text(row, "k:P_11"),
            "vat_rate": _text(row, "k:P_12"),
        })

    pay = fa.find("k:Platnosc", _N)
    paid = _text(pay, "k:Zaplacono")

    flags = []
    if currency != "PLN":
        flags.append("foreign_currency")
    if any(v["rate"] == "oo" for v in vat_lines):
        flags.append("reverse_charge")
    if direction == "purchase" and not buyer["is_company"]:
        flags.append("buyer_not_company")
    if seller["tax_id"] is None:
        flags.append("missing_tax_id")
    warnings = [] if fx or currency == "PLN" else [f"No NBP rate for {currency} before {issue_date}; gross_base empty"]

    return {
        "id": "doc_" + raw_item["id"].removeprefix("raw_"),
        "company_id": company["id"],
        "raw_item_ids": [raw_item["id"]],
        "duplicate_of": None,
        "doc_type": DOC_TYPE.get(_text(fa, "k:RodzajFaktury") or "VAT", "other"),
        "direction": direction,
        "channel": "ksef",
        "number": _text(fa, "k:P_2"),
        "issue_date": issue_date,
        "sale_date": _text(fa, "k:P_6"),
        "due_date": _text(pay, "k:TerminPlatnosci/k:Termin"),
        "seller": seller,
        "buyer": buyer,
        "totals": {
            "net": money(net_sum, currency) if vat_lines else None,
            "vat": money(vat_sum, currency) if vat_lines else None,
            "gross": gross,
            "gross_base": gross_base,
            "fx": fx,
        },
        "vat_lines": vat_lines,
        "lines": lines,
        "payment": {
            "method": PAYMENT_METHOD.get(_text(pay, "k:FormaPlatnosci") or "", "unknown"),
            "card_last4": None,
            "paid": True if paid == "1" else None,
            "paid_date": _text(pay, "k:DataZaplaty"),
            "bank_account": _text(pay, "k:RachunekBankowy/k:NrRB"),
        },
        "submitted_by": None,
        "extraction": {"method": "xml_parse", "model": None, "confidence": 1.0, "field_confidence": {},
                       "warnings": warnings, "trace_id": None},
        "category_suggestion": None,  # set later by counterparty.py
        "status": "extracted",
        "flags": flags,
        "created_at": raw_item["fetched_at"],
    }
