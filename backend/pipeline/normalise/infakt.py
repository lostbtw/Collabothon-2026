"""inFakt invoice JSON (the company's own sales invoices) -> Document; money as integer grosze or decimal units."""
from decimal import Decimal

from .fx import to_base
from .money import money, to_decimal

PAYMENT_METHOD = {"transfer": "transfer", "cash": "cash", "card": "card", "direct_debit": "direct_debit"}
DOC_TYPE = {"vat": "invoice", "proforma": "proforma", "correction": "credit_note", "advance": "invoice",
            "final": "invoice", "margin": "invoice"}


def _amount(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return Decimal(value) / 100
    return to_decimal(value)


def parse_infakt(invoice: dict, raw_item: dict, company: dict, rates=None) -> dict:
    """`company` needs `id`, `name`, `tax_id`; it is the seller on its own sales invoices."""
    currency = invoice.get("currency") or "PLN"
    gross = money(_amount(invoice["gross_price"]), currency)
    issue_date = invoice.get("invoice_date")
    gross_base, fx = to_base(gross, issue_date, rates)
    net, vat = _amount(invoice.get("net_price")), _amount(invoice.get("tax_price"))

    vat_by_rate: dict[str, list[Decimal]] = {}
    lines = []
    for s in invoice.get("services") or []:
        rate = str(s.get("tax_symbol") or "")
        line_net, line_vat = _amount(s.get("net_price")) or Decimal(0), _amount(s.get("tax_price")) or Decimal(0)
        acc = vat_by_rate.setdefault(rate, [Decimal(0), Decimal(0)])
        acc[0] += line_net
        acc[1] += line_vat
        unit = _amount(s.get("unit_net_price"))
        qty = s.get("quantity")
        lines.append({
            "description": s.get("name") or "",
            "quantity": float(qty) if qty is not None else None,
            "unit_price": money(unit, currency)["amount"] if unit is not None else None,
            "net": money(line_net, currency)["amount"],
            "vat_rate": rate or None,
        })

    tax_id = invoice.get("client_tax_code") or None
    street = " ".join(x for x in (invoice.get("client_street"), invoice.get("client_street_number")) if x)
    city = " ".join(x for x in (invoice.get("client_post_code"), invoice.get("client_city")) if x)
    status = invoice.get("status")

    return {
        "id": "doc_" + raw_item["id"].removeprefix("raw_"),
        "company_id": company["id"],
        "raw_item_ids": [raw_item["id"]],
        "duplicate_of": None,
        "doc_type": DOC_TYPE.get(str(invoice.get("kind") or "vat"), "other"),
        "direction": "sale",
        "channel": "accounting_api",
        "number": invoice.get("number"),
        "issue_date": issue_date,
        "sale_date": invoice.get("sale_date"),
        "due_date": invoice.get("payment_date"),
        "seller": {"counterparty_id": None, "name": company.get("name") or company["id"],
                   "tax_id": company.get("tax_id"), "country": "PL", "address": None},
        "buyer": {"counterparty_id": None, "name": invoice.get("client_company_name") or "(no name)",
                  "tax_id": tax_id, "country": invoice.get("client_country") or None,
                  "address": ", ".join(x for x in (street, city) if x) or None, "is_company": tax_id is not None},
        "totals": {
            "net": money(net, currency) if net is not None else None,
            "vat": money(vat, currency) if vat is not None else None,
            "gross": gross,
            "gross_base": gross_base,
            "fx": fx,
        },
        "vat_lines": [{"rate": r, "net": money(n, currency)["amount"], "vat": money(v, currency)["amount"]}
                      for r, (n, v) in vat_by_rate.items()],
        "lines": lines,
        "payment": {
            "method": PAYMENT_METHOD.get(invoice.get("payment_method") or "", "unknown"),
            "card_last4": None,
            "paid": True if status == "paid" else False if status in ("sent", "printed") else None,
            "paid_date": invoice.get("paid_date"),
            "bank_account": invoice.get("bank_account") or None,
        },
        "submitted_by": None,
        "extraction": {"method": "api", "model": None, "confidence": 1.0, "field_confidence": {},
                       "warnings": [], "trace_id": None},
        "category_suggestion": None,
        "status": "extracted",
        "flags": ["foreign_currency"] if currency != "PLN" else [],
        "created_at": raw_item["fetched_at"],
    }
