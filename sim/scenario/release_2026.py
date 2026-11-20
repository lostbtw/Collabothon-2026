#!/usr/bin/env python3
"""Borsuk Labs (SAMPLE): ground truth and release plan.

Writes:
  out/ground_truth.json  who really paid, which documents are duplicates, which bank line belongs
                         to which document, and why the other bank lines have no document
  out/release_plan.json  what role 2's releaser (#37) sends, when, and through which channel
Reads out/fa3_index.json and out/november_documents.json, so run fa3_2026.py and november_2026.py first.
No randomness: the output is byte-identical on every run.

Usage: python3 sim/scenario/release_2026.py
"""
import json
from datetime import date, timedelta

from bank_2026 import CARD_EUR, PRIVATE_ON_COMPANY, build
from november_2026 import FOREIGN, VENDOR_SENDER
from world import ACCOUNTS, AS_OF, COMPANY_ID, OUT

NOVEMBER = date(2026, 11, 1)
SCENARIO_ROOT = "sim/scenario/out/"
FOREIGN_PAYERS = set(FOREIGN) | {payer for _, payer, *_ in CARD_EUR}
PRIVATE_PAYERS = {payer for _, payer, _ in PRIVATE_ON_COMPANY.values()} | {"SPA PERLA (SAMPLE)"}
DRIP_GAPS = [30, 25, 35, 20, 40]  # seconds between dripped items (20-40 s, #37)


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def fa3_truth(e):
    bank = e["bank_line"]
    if e["direction"] == "sale":
        paid_by, match = None, "sales_invoice_payment" if bank else "document_no_transaction"
    elif e["payment"] == "cash":
        paid_by, match = "company_account", "document_no_transaction"  # M8: paid in cash
    else:
        paid_by = "owner_private" if bank["account"] == "acc_owner" else "company_account"
        match = "document_transaction"
    return {
        "document_id": e["id"], "source": "fa3", "artefact": SCENARIO_ROOT + e["file"], "direction": e["direction"],
        "doc_type": "invoice", "number": e["number"], "issue_date": e["issue_date"],
        "gross": e["gross"], "paid_by": paid_by, "paid_by_person_id": "per_tomek" if paid_by == "owner_private" else None,
        "payment_method": e["payment"], "match_type": match,
        "bank_line": {"account": bank["account"], "entry_reference": bank["entry_reference"]} if bank else None,
        "duplicate_of": None, "vat_deductible": e["direction"] == "purchase", "vat_lost": None,
        "messiness": e["messiness"],
    }


def november_truth(e):
    bank = e["bank_line"]
    if e["duplicate_of"]:
        match = "duplicate_document"
    elif bank:
        match = "document_transaction"
    else:
        match = "document_no_transaction"  # employee receipts (reimbursement owed 30 Nov), Lakeshore (open)
    no_company_buyer = "vat_not_deductible" in e["flags"]
    receipt_over_limit = e["doc_type"] == "receipt" and not no_company_buyer
    deductible = e["direction"] == "purchase" and not no_company_buyer and not receipt_over_limit
    return {
        "document_id": e["id"], "source": "november", "artefact": e["artefact"], "direction": e["direction"],
        "doc_type": e["doc_type"], "number": e["number"], "issue_date": e["issue_date"],
        "gross": {"amount": e["totals"]["gross"], "currency": e["currency"]},
        "paid_by": e["paid_by"], "paid_by_person_id": e["paid_by_person_id"],
        "payment_method": e["payment"]["method"], "match_type": match,
        "bank_line": {"account": bank["account"], "entry_reference": bank["entry_reference"]} if bank else None,
        "duplicate_of": e["duplicate_of"],
        "vat_deductible": deductible if e["direction"] == "purchase" else None,
        "vat_lost": ({"amount": e["totals"]["vat"], "currency": e["currency"]}
                     if e["direction"] == "purchase" and not deductible and not e["duplicate_of"] else None),
        "messiness": e["messiness"],
    }


def no_document_reason(acc, ttype, payer, booking):
    if ttype == "BANK FEE":
        return "bank_fee", ["M7"]
    if ttype in ("TAX OFFICE TRANSFER", "DIRECT DEBIT") and acc != "acc_owner":
        return "tax_or_social_security", []
    if ttype == "SALARY PAYMENT" or (acc == "acc_owner" and ttype == "INCOMING TRANSFER"):
        return "salary", []
    if ttype == "OUTGOING TRANSFER":
        return "reimbursement_payout", []  # the receipts behind Jan-Oct payouts are not in the scenario
    if ttype == "INTERNAL TRANSFER":
        return "internal_transfer", []
    if payer in PRIVATE_PAYERS:
        return "private_purchase_on_company_account", ["M4"]
    if payer in FOREIGN_PAYERS:
        return ("document_missing", ["M7"]) if booking >= NOVEMBER else ("foreign_invoice_not_in_backfill", [])
    if acc == "acc_owner":
        return "private", []
    return "document_missing", ["M7"]


def ground_truth(book, fa3, nov):
    documents = [fa3_truth(e) for e in fa3] + [november_truth(e) for e in nov]
    linked = {(d["bank_line"]["account"], d["bank_line"]["entry_reference"]) for d in documents if d["bank_line"]}
    without = []
    for acc in ACCOUNTS:
        for ref, _, (booking, _, ttype, reference, payer, _, amount) in book.ordered(acc):
            if (acc, ref) in linked:
                continue
            reason, messiness = no_document_reason(acc, ttype, payer, booking)
            without.append({"account": acc, "entry_reference": ref, "booking_date": booking.isoformat(),
                            "amount": {"amount": f"{amount}", "currency": ACCOUNTS[acc]["currency"]},
                            "reference": reference, "reason": reason, "messiness": messiness})
    clusters = {}
    for d in documents:
        if d["duplicate_of"]:
            clusters.setdefault(d["duplicate_of"], []).append(d["document_id"])
    duplicates = [{"cluster_id": f"dup_{i:02d}", "original": original, "copies": copies}
                  for i, (original, copies) in enumerate(sorted(clusters.items()), start=1)]
    reasons = {}
    for w in without:
        reasons[w["reason"]] = reasons.get(w["reason"], 0) + 1
    return {
        "company_id": COMPANY_ID, "as_of": AS_OF.isoformat(),
        "summary": {"documents": len(documents), "duplicate_clusters": len(duplicates),
                    "bank_lines": sum(len(r) for r in book.rows.values()),
                    "bank_lines_with_document": len(linked), "bank_lines_without_document": reasons},
        "documents": documents, "duplicates": duplicates, "bank_lines_without_document": without,
    }


def release_plan(book, fa3, nov):
    items = []
    for acc in ACCOUNTS:
        for ref, _, (booking, *_rest) in book.ordered(acc):
            items.append({"mode": "backfill", "scenario_date": booking.isoformat(), "channel": "bank",
                          "artefact": f"{SCENARIO_ROOT}bank_{acc}.csv", "account": acc, "entry_reference": ref,
                          "document_id": None, "sender": None, "via_model": False})
    for e in fa3:
        sale = e["direction"] == "sale"
        items.append({"mode": "backfill", "scenario_date": e["issue_date"],
                      "channel": "accounting_api" if sale else "email", "fallback_channel": "email" if sale else None,
                      "artefact": SCENARIO_ROOT + e["file"], "account": None, "entry_reference": None,
                      "document_id": e["id"],
                      "sender": "owner@borsuk-labs.sample" if sale else
                      ("owner@borsuk-labs.sample" if (e["bank_line"] or {}).get("account") == "acc_owner"
                       else VENDOR_SENDER),
                      "via_model": False})
    drip = []
    for e in nov:
        arrives = min(date.fromisoformat(e["issue_date"]) + timedelta(days=e["arrives_days_after_issue"]),
                      AS_OF - timedelta(days=1))
        item = {"mode": "backfill", "scenario_date": arrives.isoformat(), "channel": e["channel"],
                "artefact": e["artefact"], "account": None, "entry_reference": None, "document_id": e["id"],
                "sender": e["sender"], "via_model": e["channel"] in ("email", "photo")}
        if e["live_in_demo"]:
            item.update(mode="live", note="Jan photographs the printed receipt with a real phone during the demo; "
                                          "the releaser sends the rendered photo only as a backup")
        elif e["duplicate_of"] or "M6" in e["messiness"]:
            item["mode"] = "drip"  # arrives during the demo: duplicates and foreign SaaS invoices
            drip.append(item)
        items.append(item)
    order = {"backfill": 0, "drip": 1, "live": 2}
    channel_order = {"bank": 0, "accounting_api": 1, "email": 2, "photo": 3}
    items.sort(key=lambda i: (order[i["mode"]], i["scenario_date"], channel_order[i["channel"]],
                              i["account"] or "", i["entry_reference"] or "", i["document_id"] or ""))
    offset = 0
    for n, i in enumerate(x for x in items if x["mode"] == "drip"):
        i["offset_seconds"] = offset
        offset += DRIP_GAPS[n % len(DRIP_GAPS)]
    for seq, i in enumerate(items, start=1):
        i["seq"] = seq
    keys = ["seq", "mode", "scenario_date", "offset_seconds", "channel", "fallback_channel", "artefact", "account",
            "entry_reference", "document_id", "sender", "via_model", "note"]
    items = [{k: i[k] for k in keys if k in i and i[k] is not None or k in ("via_model",)} for i in items]
    counts = {}
    for i in items:
        counts[f"{i['mode']}/{i['channel']}"] = counts.get(f"{i['mode']}/{i['channel']}", 0) + 1
    return {
        "company_id": COMPANY_ID, "as_of": AS_OF.isoformat(),
        "artefact_roots": {
            "sim/scenario/out/": "committed scenario output (bank CSVs, FA(3) XML)",
            "november/": "PDFs and photos rendered by role 3 (#16) from sim/scenario/out/november_documents.json",
        },
        "modes": {
            "backfill": "before the demo, as fast as the pipeline allows, in scenario_date order",
            "drip": "during the demo, offset_seconds after the drip starts",
            "live": "during the demo, by hand (real phone photo)",
        },
        "channels": {
            "bank": "Sandbox Bank: POST /admin/load-csv per account gives the same entry references, "
                    "or POST /admin/transactions per line",
            "email": "SMTP to the test mailbox from `sender`",
            "photo": "e-mail with the photo attached, from `sender`",
            "accounting_api": "inFakt API when available, else `fallback_channel`",
        },
        "senders": sorted({i["sender"] for i in items if i.get("sender")}),
        "counts": dict(sorted(counts.items())),
        "items": items,
    }


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    book = build()
    fa3, nov = load("fa3_index.json"), load("november_documents.json")
    truth = ground_truth(book, fa3, nov)
    plan = release_plan(book, fa3, nov)
    write("ground_truth.json", truth)
    write("release_plan.json", plan)
    print(f"out/ground_truth.json: {truth['summary']}")
    print(f"out/release_plan.json: {len(plan['items'])} items {plan['counts']}")
    early = [i for i in plan["items"] if i["via_model"] and i["scenario_date"] < NOVEMBER.isoformat()]
    if early:
        raise SystemExit(f"release plan FAILED: {len(early)} items before November go through extraction")


if __name__ == "__main__":
    main()
