#!/usr/bin/env python3
"""Borsuk Labs (SAMPLE): the November documents (1-20 Nov 2026) that go through extraction.

Writes out/november_documents.json: the values of every November invoice and receipt, for role 3
to render as PDF or photo (#16). Every value comes from the bank generator or the story items, so
the documents, the bank lines and the story always agree.

Contents: the 10 reimbursement receipts (the hero receipt doc_rcpt412 included), company-card
receipts and invoices, foreign SaaS invoices (M6), owner's-card invoices (M3), the Lakeshore sales
invoice, and duplicates (M5). About half of the small daily card purchases have no document (M7).
No randomness: the output is byte-identical on every run.

Usage: python3 sim/scenario/november_2026.py
"""
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from bank_2026 import build
from fa3_2026 import BORSUK, PARTIES, collect as fa3_collect
from story_2026 import RECEIPTS
from world import AS_OF, OUT, PERSON

FIRST, LAST = date(2026, 11, 1), date(2026, 11, 20)
CENT = Decimal("0.01")
VENDOR_SENDER = "faktury@dostawcy.sample"  # supplier invoices by e-mail

# Private cards of the team (receipts paid privately).
CARDS = {"per_tomek": "9021", "per_jan": "7730", "per_marta": "3318", "per_anna": "5521", "per_piotr": "6604",
         "per_karolina": "2287", "per_michal": "8842"}

# Foreign vendors (not in KSeF): invoices are English PDFs by e-mail, VAT reverse charge.
FOREIGN = {
    "CODEHARBOR INC (SAMPLE)": ("CodeHarbor Inc. (SAMPLE)", "US", "EIN 99-0000101",
                                ("999 Market Street", "San Francisco, CA 94199"), "Team plan, 12 seats, monthly"),
    "CLOUDNEST BV (SAMPLE)": ("Cloudnest B.V. (SAMPLE)", "NL", "NL999999101B01",
                              ("Keizersgracht 999", "1099 AA Amsterdam"), "Cloud hosting, monthly"),
    "NOTEFORGE LTD (SAMPLE)": ("Noteforge Ltd (SAMPLE)", "IE", "IE9999101X",
                               ("99 Harbour Road", "Dublin D99 X999"), "Workspace, 7 users, monthly"),
    "MAILFOX INC (SAMPLE)": ("Mailfox Inc. (SAMPLE)", "US", "EIN 99-0000102",
                             ("999 Peachtree St", "Atlanta, GA 30399"), "E-mail delivery, monthly"),
    "TASKLOOM INC (SAMPLE)": ("Taskloom Inc. (SAMPLE)", "US", "EIN 99-0000103",
                              ("999 Mission St", "San Francisco, CA 94199"), "Project management, monthly"),
    "SIGNDESK BV (SAMPLE)": ("Signdesk B.V. (SAMPLE)", "NL", "NL999999102B01",
                             ("Prinsengracht 999", "1099 AB Amsterdam"), "E-signature, monthly"),
    "LOGBEAR INC (SAMPLE)": ("Logbear Inc. (SAMPLE)", "US", "EIN 99-0000104",
                             ("999 Pine St", "Seattle, WA 98199"), "Log monitoring, monthly"),
    "PIXELBOARD INC (SAMPLE)": ("Pixelboard Inc. (SAMPLE)", "US", "EIN 99-0000105",
                                ("999 Folsom St", "San Francisco, CA 94199"), "Whiteboard, monthly"),
    "FIGMENT DESIGN INC (SAMPLE)": ("Figment Design Inc. (SAMPLE)", "US", "EIN 99-0000106",
                                    ("999 Broadway", "New York, NY 10099"), "Design tool, 1 editor, monthly"),
    "LINGUA BRIDGE GMBH (SAMPLE)": ("Lingua Bridge GmbH (SAMPLE)", "DE", "DE999999101",
                                    ("Spreeweg 999", "10999 Berlin"), None),
}
# Polish sellers whose card purchases come as a photographed receipt; the others e-mail a PDF invoice.
RECEIPT_SELLERS = {"PALIWEX SP Z O O (SAMPLE)", "NORDPETRO S.A. (SAMPLE)", "BISTRO PIOTRKOWSKA 90 (SAMPLE)",
                   "SUSHI KAMIEN (SAMPLE)", "KAWIARNIA ZIARNO (SAMPLE)", "KOSZYK 24 SP Z O O (SAMPLE)",
                   "TAXIGO SP Z O O (SAMPLE)"}
# M12: photo defects for role 3 to render, given to the photos in order.
DEFECTS = ["rotated_8deg", "blur", "shadow", "crumpled", "low_light", "cropped_edge", "perspective", "glare"]
# M5: duplicates. (bank reference of the original, format of the copy, sender of the copy, days later)
DUPLICATES = {
    "PALIWEX 112 LODZ KARTA *4417": ("pdf", VENDOR_SENDER, 1),
    "HOTEL CENTRUM WARSZAWA KARTA *9021": ("photo", "owner@borsuk-labs.sample", 1),
    "CZYNSZ 11/2026 BIURO 4B FV CW/11/2026/017": ("pdf", VENDOR_SENDER, 5),
    "CODEHARBOR.IO* SAN FRANCISCO 420.00 USD KARTA *4417": ("pdf", "owner@borsuk-labs.sample", 1),
}


def money(x):
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def amounts(gross, rate):
    gross = money(gross)
    if rate in ("np", "np I", "np II"):
        return gross, Decimal("0.00"), gross
    net = money(gross / (1 + Decimal(rate) / 100))
    return net, gross - net, gross


def party(p):
    return {"name": p["name"], "tax_id": p.get("nip"), "country": p["country"], "address": list(p["addr"])}


def borsuk():
    return {"name": BORSUK["name"], "tax_id": BORSUK["nip"], "country": "PL", "address": list(BORSUK["addr"])}


def lines(description, rate, net, vat, gross):
    return [{"description": description, "quantity": "1", "unit_price_net": f"{net}", "net": f"{net}",
             "vat_rate": rate, "vat": f"{vat}", "gross": f"{gross}"}]


def from_bank(d, book):
    """One November document from the invoice data attached to a bank line."""
    bank = d["bank"]
    payer = d["party"]
    owner_card = bank["account"] == "acc_owner"
    paid_by, person = ("owner_private", "per_tomek") if owner_card else ("company_account", None)
    entry = {
        "paid_by": paid_by, "paid_by_person_id": person,
        "bank_line": {"account": bank["account"],
                      "entry_reference": book.entry_reference(bank["account"], bank["row_index"]),
                      "booking_date": bank["booking_date"].isoformat(), "reference": bank["reference"],
                      "amount": {"amount": f"{bank['amount']}", "currency": bank["currency"]}},
        "messiness": list(d.get("messiness", [])),
        "issue_date": d["issue"].isoformat(),
        "due_date": d["due"].isoformat() if d.get("due") else None,
    }
    if d["pay"] == "card":
        card = "9021" if owner_card else "4417"
        entry["payment"] = {"method": "card", "card_last4": card, "paid_date": d["paid"].isoformat(),
                            "bank_account": None}
    else:
        entry["payment"] = {"method": "transfer", "card_last4": None, "paid_date": None,
                            "bank_account": d.get("party_account") or None}
    sender = "owner@borsuk-labs.sample" if owner_card else VENDOR_SENDER

    if d.get("foreign"):
        name, country, tax_id, addr, line = FOREIGN[payer]
        net, vat, gross = amounts(d["gross"], "np")
        entry.update(
            kind="invoice", doc_type="invoice", format="pdf", language="en", sender=sender,
            seller={"name": name, "tax_id": tax_id, "country": country, "address": list(addr)}, buyer=borsuk(),
            number=d.get("number") or f"INV-2026-11-{1001 + list(FOREIGN).index(payer)}",
            currency=d["currency"], lines=lines(d.get("line") or line, "np", net, vat, gross),
            totals={"net": f"{net}", "vat": f"{vat}", "gross": f"{gross}"},
            flags=["foreign_currency", "reverse_charge"], note="VAT reverse charge (buyer accounts for VAT)")
        entry["messiness"] += ["M6"] if d["pay"] == "card" else []
        return entry

    p = PARTIES[payer]
    net, vat, gross = amounts(abs(bank["amount"]), p["rate"])
    photo = payer in RECEIPT_SELLERS
    entry.update(
        kind="receipt" if photo else "invoice",
        doc_type=("simplified_invoice" if gross <= 450 else "receipt") if photo else "invoice",
        format="photo" if photo else "pdf", language="pl",
        sender="owner@borsuk-labs.sample" if photo or owner_card else VENDOR_SENDER,
        seller=party(p), buyer=borsuk(),
        number=d.get("number") or f"{'PARAGON' if photo else 'FV'}/{p['prefix']}/{bank['row_index']:05d}/11/2026",
        currency="PLN", lines=lines(d.get("line") or p["line"], p["rate"], net, vat, gross),
        totals={"net": f"{net}", "vat": f"{vat}", "gross": f"{gross}"}, flags=[])
    if photo and gross <= 450:  # receipt with the company NIP up to 450 PLN counts as an invoice
        entry["messiness"].append("M11")
    return entry


def receipt(doc_id, pid, bought, seller_name, what, amount, case, company_nip, live):
    """A receipt paid with a team member's private card (reimbursement owed on 30 Nov)."""
    p = next(v for v in PARTIES.values() if v["name"] == seller_name)
    net, vat, gross = amounts(amount, p["rate"])
    invoice_in_own_name = case == "M1" and gross > 450 and doc_id != "doc_rcpt412"
    if company_nip:
        buyer = borsuk()
    elif invoice_in_own_name:
        buyer = {"name": PERSON[pid]["name"], "tax_id": None, "country": "PL", "address": None}
    else:
        buyer = None
    flags = [] if company_nip else ["buyer_not_company", "vat_not_deductible", "missing_tax_id"]
    doc_type = "invoice" if invoice_in_own_name else ("simplified_invoice" if company_nip and gross <= 450 else
                                                      "receipt")
    if doc_id == "doc_rcpt412":  # same values as contracts/fixtures/document.json
        number = "PARAGON 004512/11/2026"
    else:
        number = f"{'FV' if invoice_in_own_name else 'PARAGON'}/{p['prefix'] or 'X'}/{doc_id[-3:]}/11/2026"
    messiness = [case] + (["M11"] if gross <= 450 else [])
    return {
        "id": doc_id, "kind": "invoice" if invoice_in_own_name else "receipt", "doc_type": doc_type,
        "format": "photo", "language": "pl", "sender": PERSON[pid]["email"], "submitted_by": pid,
        "paid_by": "employee_private", "paid_by_person_id": pid,
        "seller": party(p), "buyer": buyer, "number": number, "issue_date": bought, "due_date": None,
        "currency": "PLN", "lines": lines(what + " (SAMPLE)" if doc_id == "doc_rcpt412" else what, p["rate"],
                                          net, vat, gross),
        "totals": {"net": f"{net}", "vat": f"{vat}", "gross": f"{gross}"},
        "payment": {"method": "card", "card_last4": CARDS[pid], "paid_date": bought, "bank_account": None},
        "bank_line": None, "flags": flags, "messiness": messiness, "live_in_demo": live,
    }


def lakeshore():
    net, vat, gross = amounts("40000.00", "np I")
    due = AS_OF + timedelta(days=45)
    return {
        "id": "nov_lakeshore", "kind": "invoice", "doc_type": "invoice", "format": "pdf", "language": "en",
        "sender": None, "channel": "accounting_api", "paid_by": None, "paid_by_person_id": None,
        "direction": "sale",
        "seller": borsuk(),
        "buyer": {"name": "Lakeshore Robotics Inc. (SAMPLE)", "tax_id": "EIN 99-0000201", "country": "US",
                  "address": ["999 Lake Shore Drive", "Chicago, IL 60699"]},
        "number": "2026/11/045", "issue_date": "2026-11-20", "due_date": due.isoformat(), "currency": "USD",
        "lines": lines("Robot fleet dashboard, software development (fixed price)", "np I", net, vat, gross),
        "totals": {"net": f"{net}", "vat": f"{vat}", "gross": f"{gross}"},
        "payment": {"method": "transfer", "card_last4": None, "paid_date": None, "bank_account": None},
        "bank_line": None, "flags": ["foreign_currency"], "messiness": [],
        "note": "FX Shield hero case: 40,000 USD, profit 8,000 PLN, due in 45 days",
    }


def november_documents():
    book = build()
    fa3_ids, fa3_numbers = {}, {}
    for d in fa3_collect(book):
        if d.get("ksef") and d.get("bank"):
            key = (d["bank"]["account"], d["bank"]["row_index"])
            fa3_ids[key], fa3_numbers[key] = d["id"], d["number"]
    nov = [d for d in book.docs if FIRST <= d["issue"] <= LAST and d.get("bank") and d["direction"] == "purchase"]
    nov.sort(key=lambda d: (d["issue"], d["bank"]["account"], d["bank"]["row_index"]))

    docs, daily_seen = [], 0
    for d in nov:
        if d.get("daily"):
            daily_seen += 1
            if daily_seen % 2 == 0:
                continue  # M7: receipt lost, the bank line has no document
        entry = from_bank(d, book)
        key = (d["bank"]["account"], d["bank"]["row_index"])
        if key in fa3_ids:  # M5: the same invoice also came from KSeF as FA(3) XML
            entry["duplicate_of"] = fa3_ids[key]
            entry["number"] = fa3_numbers[key]  # a copy of an invoice carries the invoice's own number
            entry["messiness"].append("M5")
            entry["flags"].append("duplicate_suspected")
        entry["_ref"] = None if d.get("daily") else d["bank"]["reference"]  # duplicates: hand-written lines only
        docs.append(entry)

    copies = []
    for entry in docs:
        if entry["_ref"] in DUPLICATES:
            fmt, sender, days = DUPLICATES[entry["_ref"]]
            copy = json.loads(json.dumps(entry))
            copy.update(format=fmt, sender=sender, arrives_days_after_issue=days, duplicate_of="__original__")
            copy["messiness"] = entry["messiness"] + ["M5"]
            copy["flags"] = entry["flags"] + ["duplicate_suspected"]
            copies.append((entry, copy))
    receipts = [receipt(*r) for r in RECEIPTS]

    everything = docs + [c for _, c in copies] + receipts + [lakeshore()]
    everything.sort(key=lambda e: (e["issue_date"], e["seller"]["name"], e["totals"]["gross"],
                                   e.get("duplicate_of") is not None, e["format"]))
    n = 0
    for e in everything:
        if not e.get("id"):
            n += 1
            e["id"] = f"nov_{n:03d}"
    for original, copy in copies:
        copy["duplicate_of"] = original["id"]
    photos = 0
    for e in everything:
        e.setdefault("duplicate_of", None)
        e.setdefault("arrives_days_after_issue", 0)
        e.setdefault("submitted_by", "per_tomek" if e["sender"] == "owner@borsuk-labs.sample" else None)
        e.setdefault("direction", "purchase")
        e.setdefault("live_in_demo", False)
        e.setdefault("channel", "photo" if e["format"] == "photo" else "email")
        e["artefact"] = f"november/{e['id']}.{'jpg' if e['format'] == 'photo' else 'pdf'}"
        e["photo_defects"] = []
        if e["format"] == "photo" and not e["live_in_demo"] and photos < len(DEFECTS):
            e["photo_defects"] = [DEFECTS[photos]]
            e["messiness"].append("M12")
            photos += 1
        e.pop("_ref", None)
    keys = ["id", "direction", "kind", "doc_type", "format", "language", "channel", "sender", "submitted_by",
            "artefact", "photo_defects", "seller", "buyer", "number", "issue_date", "due_date", "currency", "lines",
            "totals", "payment", "paid_by", "paid_by_person_id", "bank_line", "duplicate_of",
            "arrives_days_after_issue", "flags", "messiness", "live_in_demo", "note"]
    return [{k: e[k] for k in keys if k in e} for e in everything]


def main():
    docs = november_documents()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "november_documents.json").write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    fmt = {}
    for d in docs:
        fmt[d["format"]] = fmt.get(d["format"], 0) + 1
    print(f"out/november_documents.json: {len(docs)} documents {fmt}, "
          f"{sum(1 for d in docs if d['duplicate_of'])} duplicates, "
          f"{sum(1 for d in docs if d['photo_defects'])} photos with defects")


if __name__ == "__main__":
    main()
