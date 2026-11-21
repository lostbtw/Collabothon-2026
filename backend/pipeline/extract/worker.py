import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import psycopg

from backend.db.events import new_event, publish
from backend.db.store import Store
from backend.pipeline.normalise.fx import StandInRates, to_base
from backend.pipeline.who_paid import consequences, document_flags

from . import docling
from .errors import ExtractionError

CONSUMER = "extractor"
PRODUCER = "extractor"
KINDS = {"upload", "email_attachment", "chat_photo"}
PERSON_ROLES = {"owner", "employee"}

Extract = Callable[[bytes, str], dict[str, Any]]


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def readable(raw: dict) -> bool:
    try:
        docling.media_type(raw.get("content_type"))
    except ExtractionError:
        return False
    return True


def nip(tax_id: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (tax_id or "").upper()).removeprefix("PL")


def channel(raw: dict) -> str:
    if raw["kind"] == "upload":
        return "upload"
    return "email" if docling.media_type(raw.get("content_type")) == docling.PDF else "photo"


def person_ref(person: dict | None) -> dict | None:
    if not person:
        return None
    role = person.get("role")
    return {"person_id": person["id"], "name": person.get("name"), "email": person.get("email"),
            "role": role if role in PERSON_ROLES else "unknown"}


def build(raw: dict, fields: dict, company: dict, *, submitted_by: dict | None, rates: Any,
          created_at: str) -> dict:
    own = nip(company.get("tax_id"))
    seller, buyer = fields["seller"], fields["buyer"]
    direction = "sale" if own and nip(seller.get("tax_id")) == own else "purchase"
    base = company.get("base_currency") or "PLN"
    gross = fields["totals"]["gross"]
    if gross["currency"] == base:
        gross_base, fx = dict(gross), None
    elif base == "PLN":
        gross_base, fx = to_base(gross, fields.get("issue_date"), rates)
    else:
        gross_base, fx = None, None
    document = {
        "id": "doc_" + raw["id"].removeprefix("raw_"),
        "company_id": company["id"],
        "raw_item_ids": [raw["id"]],
        "duplicate_of": None,
        **fields,
        "direction": direction,
        "channel": channel(raw),
        "buyer": {**buyer, "is_company": bool(own) and nip(buyer.get("tax_id")) == own},
        "totals": {**fields["totals"], "gross_base": gross_base, "fx": fx},
        "submitted_by": submitted_by,
        "created_at": created_at,
    }
    flags = list(fields.get("flags") or [])
    if gross["currency"] != base:
        flags.append("foreign_currency")
    if any(line["rate"] == "oo" for line in document["vat_lines"]):
        flags.append("reverse_charge")
    if not seller.get("tax_id"):
        flags.append("missing_tax_id")
    document["flags"] = list(dict.fromkeys(flags))
    company_info = {**company, "tax_id": company.get("tax_id") or ""}
    document["flags"] = document_flags(document, consequences(document, "unknown", None, company_info))
    return document


def extracted_payload(doc: dict) -> dict:
    return {"document_id": doc["id"], "status": doc["status"], "gross": doc["totals"]["gross"],
            "seller": doc["seller"]["name"], "flags": doc.get("flags", [])}


class Postgres:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.store = Store(conn)

    def company(self, company_id: str) -> dict:
        row = self.conn.execute("select to_jsonb(c) from companies c where id = %s", (company_id,)).fetchone()
        return dict(row[0]) if row else {"id": company_id}

    def person(self, company_id: str, value: str | None) -> dict | None:
        value = (value or "").strip()
        if not value:
            return None
        row = self.conn.execute(
            """select p.id, p.name, p.email, p.role from people p
               where p.company_id = %(c)s and (p.id = %(v)s or lower(p.email) = lower(%(v)s)
                 or p.id = (select person_id from person_addresses where address = lower(%(v)s)))
               limit 1""", {"c": company_id, "v": value}).fetchone()
        return dict(zip(("id", "name", "email", "role"), row)) if row else None

    def submitted_by(self, company_id: str, raw: dict) -> dict | None:
        meta = raw.get("metadata") or {}
        candidates = [meta.get("submitted_by"), meta.get("forwarded_by"), meta.get("from")]
        if raw.get("parent_raw_item_id"):
            parent = self.store.get("raw_item", raw["parent_raw_item_id"]) or {}
            parent_meta = parent.get("metadata") or {}
            candidates += [parent_meta.get("forwarded_by"), parent_meta.get("from")]
        for value in candidates:
            person = self.person(company_id, value)
            if person:
                return person_ref(person)
        return None

    def content(self, raw: dict) -> bytes | None:
        row = self.conn.execute("select bytes from raw_item_content where raw_item_id = %s", (raw["id"],)).fetchone()
        if row:
            return bytes(row[0])
        uri = raw.get("storage_uri") or ""
        if uri.startswith("pvc://raw/"):
            path = Path(os.environ.get("ORDO_RAW_DIR", "/data/raw")) / uri.removeprefix("pvc://raw/")
            if path.is_file():
                return path.read_bytes()
        return None

    def set_status(self, raw: dict, company_id: str, status: str, error: dict | None = None) -> None:
        self.store.put("raw_item", {**raw, "processing_status": status, "error": error}, company_id=company_id)


def handle(conn: psycopg.Connection, event: dict, extract: Extract, *, rates: Any = None) -> str:
    db = Postgres(conn)
    company_id = event["company_id"]
    raw = db.store.get("raw_item", event["payload"]["raw_item_id"])
    if raw is None or raw["kind"] not in KINDS:
        return "skipped"
    if not readable(raw):
        if raw["kind"] == "upload":
            db.set_status(raw, company_id, "ignored", {"code": "unsupported_content_type", "retryable": False,
                                                       "message": f"Cannot read {raw.get('content_type')} files"})
            return "ignored"
        return "skipped"
    if db.store.list("document", first_raw_item_id=raw["id"]):
        db.set_status(raw, company_id, "processed")
        return "exists"
    data = db.content(raw)
    if data is None:
        db.set_status(raw, company_id, "failed", {"code": "content_missing", "retryable": False,
                                                  "message": "The file of this item is not stored"})
        return "failed"
    db.set_status(raw, company_id, "processing")
    fields = extract(data, raw["content_type"])
    company = db.company(company_id)
    document = build(raw, fields, company, submitted_by=db.submitted_by(company_id, raw),
                     rates=rates if rates is not None else StandInRates(), created_at=now_iso())
    publish(conn, new_event("document.extracted", company_id, extracted_payload(document), producer=PRODUCER,
                            correlation_id=event.get("correlation_id") or raw["id"], causation_id=event["id"]),
            commit=False)
    db.store.add("document", document, company_id=company_id)
    db.set_status(raw, company_id, "processed")
    return "extracted"


def fail(conn: psycopg.Connection, event: dict, error: Exception) -> None:
    db = Postgres(conn)
    raw = db.store.get("raw_item", event["payload"]["raw_item_id"])
    if raw is not None and raw["kind"] in KINDS:
        db.set_status(raw, event["company_id"], "failed",
                      {"code": "extraction_failed", "message": str(error)[:500], "retryable": True})
