#!/usr/bin/env python3
"""Printable SAMPLE receipts and their ground truth (ticket #16). Stdlib only.

    python sim/documents/receipts/receipts.py            # writes sim/documents/receipts/out/

Outputs:
- out/print_sheet.html : all receipts (with copies) on A4, cut along the dashed lines. Print at 100% scale.
- out/<id>.html        : one receipt per file.
- receipts_truth.json  : the values a reader should extract, per receipt (committed; role 1 evaluates against it).

Every receipt carries SAMPLE in the seller line, a footer and a diagonal watermark (D-18). Totals and VAT are
computed here (VAT included in the price, Polish fiscal-receipt style), so the printout and the truth agree.
"""
import html
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CENT = Decimal("0.01")


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def pl(x: Decimal) -> str:
    """1299.00 -> '1299,00' (Polish receipts use a decimal comma)."""
    return format(q(x), "f").replace(".", ",")


def nip_dashed(nip: str) -> str:
    return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}"


def compute(receipt: dict, rates: dict) -> dict:
    """Line totals, VAT per letter (from gross), grand total."""
    lines, by_letter = [], {}
    for item in receipt["items"]:
        qty, unit = Decimal(item["quantity"]), Decimal(item["unit_price"])
        total = q(qty * unit)
        lines.append({**item, "total": total})
        by_letter[item["vat"]] = by_letter.get(item["vat"], Decimal(0)) + total
    vat_lines = []
    for letter, gross in sorted(by_letter.items()):
        rate = Decimal(rates[letter])
        vat = q(gross * rate / (100 + rate))
        vat_lines.append({"letter": letter, "rate": rates[letter], "gross": gross, "vat": vat, "net": gross - vat})
    gross = sum(v["gross"] for v in vat_lines)
    vat = sum(v["vat"] for v in vat_lines)
    return {"lines": lines, "vat_lines": vat_lines, "gross": gross, "vat": vat, "net": gross - vat}


def truth(receipt: dict, c: dict) -> dict:
    """Ground truth in the Document field names role 1 extracts (contracts/schemas/document.schema.json)."""
    return {
        "id": receipt["id"],
        "purpose": receipt["purpose"],
        "doc_type": "receipt",
        "number": receipt["number"],
        "issue_date": receipt["issue_date"],
        "seller": {"name": receipt["seller"]["name"], "tax_id": receipt["seller"]["tax_id"]},
        "buyer": {"tax_id": receipt["buyer_tax_id"], "is_company": receipt["buyer_tax_id"] is not None},
        "totals": {"net": {"amount": str(c["net"]), "currency": "PLN"},
                   "vat": {"amount": str(c["vat"]), "currency": "PLN"},
                   "gross": {"amount": str(c["gross"]), "currency": "PLN"}},
        "vat_lines": [{"rate": v["rate"], "net": str(v["net"]), "vat": str(v["vat"])} for v in c["vat_lines"]],
        "lines": [{"description": l["description"], "quantity": float(l["quantity"]),
                   "unit_price": l["unit_price"], "vat_rate": None} for l in c["lines"]],
        "payment": {"method": receipt["payment"]["method"], "card_last4": receipt["payment"].get("card_last4")},
    }


def receipt_html(receipt: dict, c: dict) -> str:
    e = html.escape
    s = receipt["seller"]
    day = receipt["issue_date"]
    rows = []
    for l in c["lines"]:
        rows.append(f'<div class="item">{e(l["description"])}</div>'
                    f'<div class="row"><span>{e(l["quantity"])} x{pl(Decimal(l["unit_price"]))}</span>'
                    f'<span>{pl(l["total"])} {e(l["vat"])}</span></div>')
    vat_rows = []
    for v in c["vat_lines"]:
        vat_rows.append(f'<div class="row"><span>Sprzed. opod. PTU {v["letter"]}</span><span>{pl(v["gross"])}</span></div>'
                        f'<div class="row"><span>Kwota PTU {v["letter"]} {v["rate"]},00%</span><span>{pl(v["vat"])}</span></div>')
    buyer = (f'<div class="center bold">NIP nabywcy: {nip_dashed(receipt["buyer_tax_id"])}</div>'
             if receipt["buyer_tax_id"] else "")
    card = receipt["payment"].get("card_last4")
    return f"""
<div class="receipt">
  <div class="watermark">SAMPLE</div>
  <div class="center bold">{e(s["name"])}</div>
  {''.join(f'<div class="center">{e(a)}</div>' for a in s["address"])}
  <div class="center">NIP {nip_dashed(s["tax_id"])}</div>
  <div class="row small"><span>{day[8:10]}.{day[5:7]}.{day[:4]} {e(receipt["time"])}</span><span>{e(receipt["number"].split()[-1])}</span></div>
  {buyer}
  <div class="center bold title">PARAGON FISKALNY</div>
  <div class="rule"></div>
  {''.join(rows)}
  <div class="rule"></div>
  {''.join(vat_rows)}
  <div class="row"><span>Suma PTU</span><span>{pl(c["vat"])}</span></div>
  <div class="row total"><span>SUMA PLN</span><span>{pl(c["gross"])}</span></div>
  <div class="rule"></div>
  <div class="row"><span>Karta płatnicza</span><span>{pl(c["gross"])} PLN</span></div>
  {f'<div class="row small"><span>Karta</span><span>**** **** **** {e(card)}</span></div>' if card else ''}
  <div class="row small"><span>{e(receipt["cashier"])}</span><span>{e(receipt["register_no"])}</span></div>
  <div class="rule"></div>
  <div class="center small footer">SAMPLE · NOT A REAL RECEIPT<br>Collabothon 2026 test document · no fiscal value</div>
</div>"""


CSS = """
@page { size: A4; margin: 8mm; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #000; font-family: "Courier New", Courier, monospace; }
.sheet { display: grid; grid-template-columns: repeat(2, 74mm); gap: 0 18mm; justify-content: center; }
.cut { border: 1px dashed #999; padding: 4mm; margin-bottom: 6mm; break-inside: avoid; }
.receipt { position: relative; width: 66mm; font-size: 9.5pt; line-height: 1.3; overflow: hidden; }
.center { text-align: center; }
.bold { font-weight: bold; }
.title { font-size: 11pt; margin-top: 2mm; letter-spacing: 1px; }
.small { font-size: 8pt; }
.row { display: flex; justify-content: space-between; gap: 2mm; }
.item { margin-top: 1mm; }
.total { font-size: 12pt; font-weight: bold; margin-top: 1mm; }
.rule { border-top: 1px dashed #000; margin: 1.5mm 0; }
.footer { margin-top: 1mm; }
.watermark { position: absolute; top: 40%; left: -10%; width: 120%; text-align: center; transform: rotate(-35deg);
  font-size: 34pt; font-weight: bold; color: rgba(0,0,0,0.10); pointer-events: none; letter-spacing: 6px; }
.label { font-family: Arial, sans-serif; font-size: 7pt; color: #777; margin-bottom: 2mm; }
@media screen { body { background: #eee; padding: 10mm 0; } .cut { background: #fff; } }
"""


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def main() -> None:
    seed = json.loads((HERE / "receipts_seed.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    cells, truths = [], []
    for r in seed["receipts"]:
        c = compute(r, seed["vat_rates"])
        truths.append(truth(r, c))
        one = receipt_html(r, c)
        (OUT / f"{r['id']}.html").write_text(page(r["id"], f'<div class="sheet"><div class="cut">{one}</div></div>'),
                                             encoding="utf-8")
        copies = r.get("copies", 1)
        for n in range(1, copies + 1):
            label = r["id"] + (f" (copy {n} of {copies})" if copies > 1 else "")
            cells.append(f'<div class="cut"><div class="label">{html.escape(label)}</div>{one}</div>')
    (OUT / "print_sheet.html").write_text(page("Ordo SAMPLE receipts", f'<div class="sheet">{"".join(cells)}</div>'),
                                          encoding="utf-8")
    (HERE / "receipts_truth.json").write_text(json.dumps(truths, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    for t in truths:
        print(f'{t["id"]:12} gross {t["totals"]["gross"]["amount"]:>8}  VAT {t["totals"]["vat"]["amount"]:>7}  '
              f'buyer NIP {t["buyer"]["tax_id"] or "-":10}  card *{t["payment"]["card_last4"]}')
    print(f"wrote {OUT / 'print_sheet.html'}")


if __name__ == "__main__":
    main()
