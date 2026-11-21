"""The whole pipeline on the demo scenario (sim/scenario/out), for comparison with ground_truth.json."""
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from backend.pipeline import counterparty, dedupe, missing
from backend.pipeline.match import run_matching
from backend.pipeline.normalise import commerzbank_csv, normalise_bank_line, parse_fa3
from backend.pipeline.normalise.fx import StandInRates, to_base
from backend.pipeline.normalise.money import money

OUT = Path(__file__).resolve().parents[3] / "sim" / "scenario" / "out"
COMPANY = {"id": "co_borsuk", "tax_id": "9990000014", "as_of_date": "2026-11-21"}
ACCOUNTS = [
    {"id": "acc_pln", "company_id": "co_borsuk", "kind": "company_bank", "currency": "PLN", "card_last4": ["4417"],
     "source_id": "src_bank_pln"},
    {"id": "acc_eur", "company_id": "co_borsuk", "kind": "company_bank", "currency": "EUR", "card_last4": ["2290"],
     "source_id": "src_bank_eur"},
    {"id": "acc_owner", "company_id": "co_borsuk", "kind": "owner_private", "currency": "PLN", "card_last4": ["9021"],
     "source_id": "src_bank_owner"},
]
rates = StandInRates()


def available() -> bool:
    return (OUT / "ground_truth.json").exists()


def people() -> list[dict]:
    raw = json.loads((OUT / "people.json").read_text(encoding="utf-8"))
    return [{"person_id": p["id"], "name": p["name"], "email": p["email"], "role": p["role"]} for p in raw]


def transactions() -> list[dict]:
    out = []
    for account in ACCOUNTS:
        lines = commerzbank_csv.read_booked_lines(OUT / f"bank_{account['id']}.csv")
        for raw in commerzbank_csv.raw_items(lines, source_id=account["source_id"], account_key=account["id"][4:]):
            out.append(normalise_bank_line(raw, account))
    return out


def fa3_documents() -> list[dict]:
    docs = []
    for path in sorted((OUT / "fa3").rglob("*.xml")):
        raw = {"id": f"raw_{path.stem}", "fetched_at": f"{path.stem[4:8]}-{path.stem[8:10]}-{path.stem[10:12]}T12:00:00Z"}
        docs.append(parse_fa3(path.read_bytes(), raw, COMPANY, rates=rates))
    return docs


def november_documents() -> tuple[list[dict], dict[str, str]]:
    docs, senders = [], {}
    for n in json.loads((OUT / "november_documents.json").read_text(encoding="utf-8")):
        doc_id = n["id"] if n["id"].startswith("doc_") else f"doc_{n['id']}"
        ccy = n["currency"]
        buyer = n.get("buyer") or {"name": "(none printed)", "tax_id": None, "country": None, "address": None}
        gross = money(n["totals"]["gross"], ccy)
        gross_base, fx = to_base(gross, n["issue_date"], rates)
        vat_lines: dict[str, list[Decimal]] = {}
        for line in n["lines"]:
            acc = vat_lines.setdefault(line["vat_rate"], [Decimal(0), Decimal(0)])
            acc[0] += Decimal(line["net"])
            acc[1] += Decimal(line["vat"])
        docs.append({
            "id": doc_id, "company_id": "co_borsuk", "raw_item_ids": [f"raw_{n['id']}"], "duplicate_of": None,
            "doc_type": n["doc_type"], "direction": n["direction"], "channel": n["channel"], "number": n["number"],
            "issue_date": n["issue_date"], "sale_date": None, "due_date": n.get("due_date"),
            "seller": {"counterparty_id": None, "name": n["seller"]["name"], "tax_id": n["seller"].get("tax_id"),
                       "country": n["seller"].get("country"), "address": ", ".join(n["seller"].get("address") or [])},
            "buyer": {"counterparty_id": None, "name": buyer["name"], "tax_id": buyer.get("tax_id"),
                      "country": buyer.get("country"),
                      "address": ", ".join(buyer.get("address") or []) or None,
                      "is_company": buyer.get("tax_id") is not None},
            "totals": {"net": money(n["totals"]["net"], ccy), "vat": money(n["totals"]["vat"], ccy), "gross": gross,
                       "gross_base": gross_base, "fx": fx},
            "vat_lines": [{"rate": r, "net": format(v[0], "f"), "vat": format(v[1], "f")} for r, v in vat_lines.items()
                          if v[1] or r not in ("np", "np II", "oo")],
            "lines": [{"description": l["description"], "quantity": float(l["quantity"]), "unit_price": l.get("unit_price_net"),
                       "net": l["net"], "vat_rate": l["vat_rate"]} for l in n["lines"]],
            "payment": {"method": n["payment"]["method"], "card_last4": n["payment"].get("card_last4"),
                        "paid": True if n["payment"].get("paid_date") else None,
                        "paid_date": n["payment"].get("paid_date"), "bank_account": n["payment"].get("bank_account")},
            "submitted_by": None,
            "extraction": {"method": "llm_vision" if n["channel"] == "photo" else "docling_llm", "model": None,
                           "confidence": 0.95, "field_confidence": {}, "warnings": [], "trace_id": None},
            "category_suggestion": None, "status": "extracted",
            "flags": [f for f in n.get("flags", []) if f in ("foreign_currency", "reverse_charge")],
            "created_at": f"{date.fromisoformat(n['issue_date']) + timedelta(days=n.get('arrives_days_after_issue', 0))}"
                          f"T12:{len(docs) % 60:02d}:00Z",
        })
        senders[doc_id] = n.get("sender")
    return docs, senders


def run() -> dict:
    txns = transactions()
    cps: list[dict] = []
    for i, t in enumerate(txns):
        txns[i], new = counterparty.apply_to_transaction(t, cps, "co_borsuk")
        if new:
            cps.append(new)
    nov, senders = november_documents()
    docs = fa3_documents() + nov
    for i, d in enumerate(docs):
        docs[i], cp = counterparty.apply_to_document(d, cps, "co_borsuk")
        if cp:
            cps = [c for c in cps if c["id"] != cp["id"]] + [cp]
    deduped = dedupe.deduplicate(docs)
    results = run_matching(deduped["documents"], txns, company=COMPANY, people=people(), accounts=ACCOUNTS,
                           now="2026-11-21T10:00:00Z", as_of=COMPANY["as_of_date"], senders=senders)
    paid = {r["match"]["transaction_id"] for r in results if r["match"]["transaction_id"]}
    kind = {a["id"]: a["kind"] for a in ACCOUNTS}
    line_status = {t["id"]: (None if kind[t["account_id"]] == "owner_private" else
                             missing.line_status(t, COMPANY["as_of_date"], lookback_days=400))
                   for t in txns if t["id"] not in paid}
    return {"transactions": txns, "documents": deduped["documents"], "merges": deduped["merges"],
            "clusters": deduped["clusters"], "results": results, "line_status": line_status, "counterparties": cps}


def truth() -> dict:
    return json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))


def doc_id(truth_id: str) -> str:
    return truth_id if truth_id.startswith("doc_") else f"doc_{truth_id}"


def txn_id(bank_line: dict | None) -> str | None:
    return f"txn_{bank_line['account'][4:]}_{bank_line['entry_reference']}" if bank_line else None
