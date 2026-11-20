"""Event handlers of the pipeline process (role 3). Consumer groups from backend/db/migrations/001_init.sql:

  normaliser  raw_item.received     bank line -> Transaction (transaction.ingested);
                                    FA(3) XML / inFakt JSON -> Document (document.extracted)
  matcher     document.extracted    dedupe (document.duplicate_detected), then match + who paid (match.suggested)
              transaction.ingested  a new bank line may pay documents that had none yet (match.suggested)
              match.decided         bank line status follows the decision; alias learning arrives with #41

Handlers get a `Context` (see main.py for the Postgres one, tests use an in-memory one), so the logic does not
depend on the database driver. Writes are idempotent: one Match per document (same id on re-match), the Store
ignores repeated Transactions and Documents.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from . import counterparty, dedupe
from .match import match_suggested_payload, run_matching
from .normalise import NormaliseError, normalise_bank_line, parse_fa3, parse_infakt, transaction_ingested_payload
from .normalise.fa3 import Fa3Error
from .normalise.fx import StandInRates
from .who_paid import document_flags

PRODUCER = "pipeline"

# STAND-IN until the companies table carries tax_id (requested from role 5 on spec #5).
COMPANY_TAX_IDS = {"co_borsuk": "9990000014"}


class Store(Protocol):
    def add(self, entity: str, doc: dict, *, company_id: str | None = None) -> bool: ...
    def put(self, entity: str, doc: dict, *, company_id: str | None = None) -> None: ...
    def get(self, entity: str, id: str) -> dict | None: ...
    def company_of(self, entity: str, id: str) -> str | None: ...
    def list(self, entity: str, *, company_id: str | None = None, **where: Any) -> list[dict]: ...


@dataclass
class Context:
    store: Store
    publish: Callable[[str, str, dict, str | None, str | None], None]  # (type, company, payload, correlation, causation)
    company: Callable[[str], dict]  # company id -> {"id", "tax_id", "as_of_date", "base_currency"}
    people: Callable[[str], list[dict]]  # company id -> PersonRefs (+ extra addresses as more entries)
    raw_bytes: Callable[[dict], bytes | None]  # RawItem -> file content (XML), or None
    rates: Any = None  # NBP rates (fx.py); StandInRates until the NBP connector (#34) lands
    now: Callable[[], str] = lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    choose: Callable[[str, list[str]], str | None] | None = None  # model picks from an enum (D-09); None = rules only


# ---------- normaliser ----------

def on_raw_item_received(ctx: Context, event: dict) -> None:
    s = ctx.store
    raw = s.get("raw_item", event["payload"]["raw_item_id"])
    if raw is None or raw["kind"] not in ("bank_transaction", "ksef_invoice_xml", "accounting_invoice"):
        return  # e-mails, photos and uploads belong to the extractor (role 1)
    company = event["company_id"]
    correlation = event.get("correlation_id") or raw["id"]
    try:
        if raw["kind"] == "bank_transaction":
            account = next((a for a in s.list("account", company_id=company) if a.get("source_id") == raw["source_id"]),
                           None)
            if account is None:
                raise NormaliseError(f"no account for source {raw['source_id']}")
            txn = normalise_bank_line(raw, account)
            txn, new_cp = counterparty.apply_to_transaction(txn, s.list("counterparty", company_id=company), company,
                                                            ctx.choose)
            if s.add("transaction", txn, company_id=company):
                if new_cp:
                    s.add("counterparty", new_cp, company_id=company)
                ctx.publish("transaction.ingested", company, transaction_ingested_payload(txn), correlation, event["id"])
        else:
            info = ctx.company(company)
            if raw["kind"] == "ksef_invoice_xml":
                xml = ctx.raw_bytes(raw) or (raw.get("payload") or {}).get("xml", "").encode()
                doc = parse_fa3(xml, raw, info, rates=ctx.rates)
            else:
                doc = parse_infakt(raw.get("payload") or {}, raw, info, rates=ctx.rates)
            if s.add("document", doc, company_id=company):
                ctx.publish("document.extracted", company, _extracted_payload(doc), correlation, event["id"])
        s.put("raw_item", {**raw, "processing_status": "processed", "error": None}, company_id=company)
    except (NormaliseError, Fa3Error, KeyError, ValueError) as exc:
        # Deterministic input problem: retrying will not help. The Sources page counts failed items.
        s.put("raw_item", {**raw, "processing_status": "failed",
                           "error": {"code": "normalise_failed", "message": str(exc)[:500], "retryable": False}},
              company_id=company)


def _extracted_payload(doc: dict) -> dict:
    return {"document_id": doc["id"], "status": doc["status"], "gross": doc["totals"]["gross"],
            "seller": doc["seller"]["name"], "flags": doc.get("flags", [])}


# ---------- matcher ----------

def _company_inputs(ctx: Context, company: str):
    info = ctx.company(company)
    accounts = ctx.store.list("account", company_id=company)
    return info, ctx.people(company), [{**a, "company_id": a.get("company_id") or company} for a in accounts]


def sender_of(ctx: Context, doc: dict) -> str | None:
    """Who forwarded the document: RawItem metadata `forwarded_by`, else the parent e-mail's `from`."""
    for raw_id in doc.get("raw_item_ids") or []:
        raw = ctx.store.get("raw_item", raw_id) or {}
        meta = raw.get("metadata") or {}
        if meta.get("forwarded_by") or meta.get("from"):
            return meta.get("forwarded_by") or meta.get("from")
        parent = ctx.store.get("raw_item", raw["parent_raw_item_id"]) if raw.get("parent_raw_item_id") else None
        if parent and (parent.get("metadata") or {}).get("from"):
            return parent["metadata"]["from"]
    return (doc.get("submitted_by") or {}).get("email")


def _existing_match(ctx: Context, document_id: str) -> dict | None:
    matches = ctx.store.list("match", document_id=document_id)
    return next((m for m in matches if m["status"] == "suggested"), matches[0] if matches else None)


def _save_match(ctx: Context, company: str, doc: dict, result: dict, correlation: str | None, causation: str) -> None:
    s = ctx.store
    match = result["match"]
    previous = _existing_match(ctx, doc["id"])
    if previous:
        if previous["status"] in ("confirmed", "auto_confirmed", "rejected") and \
                (previous.get("decided_by") or {}).get("role") != "system":
            return  # the owner already decided this document
        match = {**match, "id": previous["id"]}  # one Match per document: re-matching replaces it
        if previous.get("transaction_id") and previous["transaction_id"] != match["transaction_id"]:
            old = s.get("transaction", previous["transaction_id"])
            if old:
                s.put("transaction", {**old, "match_status": "unmatched"}, company_id=company)
    s.put("match", match, company_id=company)
    if match["transaction_id"]:
        txn = s.get("transaction", match["transaction_id"])
        if txn:
            status = "matched" if match["status"] == "auto_confirmed" else "suggested"
            s.put("transaction", {**txn, "match_status": status}, company_id=company)
    flags = document_flags(doc, match["consequences"])
    if flags != doc.get("flags"):
        s.put("document", {**doc, "flags": flags}, company_id=company)
    ctx.publish("match.suggested", company, match_suggested_payload(match), correlation, causation)


def match_document(ctx: Context, company: str, doc: dict, correlation: str | None, causation: str) -> None:
    info, people, accounts = _company_inputs(ctx, company)
    txns = ctx.store.list("transaction", company_id=company, match_status="unmatched")
    previous = _existing_match(ctx, doc["id"])
    if previous and previous.get("transaction_id"):  # its own line stays a candidate when re-matching
        own = ctx.store.get("transaction", previous["transaction_id"])
        if own and own not in txns:
            txns.append({**own, "match_status": "unmatched"})
    [result] = run_matching([doc], txns, company=info, people=people, accounts=accounts, now=ctx.now(),
                            as_of=info.get("as_of_date"), senders={doc["id"]: sender_of(ctx, doc)})
    _save_match(ctx, company, doc, result, correlation, causation)


def on_document_extracted(ctx: Context, event: dict) -> None:
    s = ctx.store
    company = event["company_id"]
    doc = s.get("document", event["payload"]["document_id"])
    if doc is None or doc.get("status") in ("rejected",):
        return
    doc = {**doc, "company_id": doc.get("company_id") or company}
    resolved, cp = counterparty.apply_to_document(doc, s.list("counterparty", company_id=company), company, ctx.choose)
    if cp:
        s.put("counterparty", cp, company_id=company)
    if resolved != doc:
        doc = resolved
        s.put("document", doc, company_id=company)
    correlation = event.get("correlation_id")
    existing = [d for d in s.list("document", company_id=company) if d["id"] != doc["id"]]
    result = dedupe.add_document(doc, existing)
    for changed in result["documents"]:
        s.put("document", changed, company_id=company)
    for merge in result["merges"]:
        ctx.publish("document.duplicate_detected", company, dedupe.duplicate_detected_payload(merge), correlation,
                    event["id"])
    current = next(d for d in result["documents"] if d["id"] == doc["id"])
    if result["golden_changed"]:
        _retire_match(ctx, company, result["golden_changed"])
    if current["status"] == "duplicate":
        _retire_match(ctx, company, current["id"])
        return
    match_document(ctx, company, current, correlation, event["id"])


def _retire_match(ctx: Context, company: str, document_id: str) -> None:
    """A copy that stopped being the golden record gives up its open Match (the golden one is matched instead)."""
    previous = _existing_match(ctx, document_id)
    if previous and previous["status"] == "suggested":
        ctx.store.put("match", {**previous, "status": "rejected", "decided_at": ctx.now(),
                                "decided_by": {"role": "system", "person_id": None, "email": None,
                                               "name": "rule: duplicate of a better copy"}}, company_id=company)
        if previous.get("transaction_id"):
            txn = ctx.store.get("transaction", previous["transaction_id"])
            if txn:
                ctx.store.put("transaction", {**txn, "match_status": "unmatched"}, company_id=company)


def on_transaction_ingested(ctx: Context, event: dict) -> None:
    """A new bank line can pay a document that had none (card lines book a day or two after the receipt)."""
    s = ctx.store
    company = event["company_id"]
    txn = s.get("transaction", event["payload"]["transaction_id"])
    if txn is None or txn.get("match_status") != "unmatched":
        return
    waiting = []
    for doc in s.list("document", company_id=company):
        if doc.get("status") in ("duplicate", "rejected"):
            continue
        previous = _existing_match(ctx, doc["id"])
        if previous and previous["status"] == "suggested" and previous["match_type"] == "document_no_transaction":
            waiting.append(doc)
    if not waiting:
        return
    info, people, accounts = _company_inputs(ctx, company)
    results = run_matching(waiting, [txn], company=info, people=people, accounts=accounts, now=ctx.now(),
                           as_of=info.get("as_of_date"), senders={d["id"]: sender_of(ctx, d) for d in waiting})
    for result in results:
        if result["match"]["transaction_id"]:
            doc = next(d for d in waiting if d["id"] == result["match"]["document_id"])
            _save_match(ctx, company, doc, result, event.get("correlation_id"), event["id"])


def on_match_decided(ctx: Context, event: dict) -> None:
    """The bank line follows the owner's decision; a confirmation also teaches the bank spelling as an alias (#41)."""
    s = ctx.store
    company = event["company_id"]
    match = s.get("match", event["payload"]["match_id"])
    if not match or not match.get("transaction_id"):
        return
    txn = s.get("transaction", match["transaction_id"])
    if txn is None:
        return
    confirmed = event["payload"]["status"] == "confirmed"
    txn = {**txn, "match_status": "matched" if confirmed else "unmatched"}
    document = s.get("document", match["document_id"]) if confirmed else None
    if document:
        cps, doc_out, txn_out = counterparty.learn_from_match(document, txn, s.list("counterparty", company_id=company),
                                                              company)
        for cp in cps:
            s.put("counterparty", cp, company_id=company)
        if doc_out:
            s.put("document", doc_out, company_id=company)
        txn = txn_out or txn
    s.put("transaction", txn, company_id=company)


HANDLERS: dict[str, dict[str, list[Callable[[Context, dict], None]]]] = {
    "normaliser": {"raw_item.received": [on_raw_item_received]},
    "matcher": {"document.extracted": [on_document_extracted],
                "transaction.ingested": [on_transaction_ingested],
                "match.decided": [on_match_decided]},
}


def default_rates():
    return StandInRates()
