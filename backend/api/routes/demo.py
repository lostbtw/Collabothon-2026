"""Stage trigger for the demo (not part of the contract): someone behind the stage opens

    https://<app>/api/v1/demo/receipt              (taxi, 800.00 PLN)
    https://<app>/api/v1/demo/receipt?receipt=bajt (computer shop, 169.98 PLN)

and Ordo receives an e-mail from the employee Jan Testowy with the receipt photo attached, exactly as the mailbox
connector would store it (role 2's `message_items`, src_mail, raw_item.received). The real pipeline then reads the
photo, matches it, makes the "Pay Jan back" to-do and updates the forecast; the open app shows the toasts and
reloads its numbers by itself.

Every call is a new e-mail: the previous demo receipt is retired first (document `rejected`, its open cards
superseded), so the duplicate check does not swallow the next one. Set ORDO_DEMO_TRIGGER=0 to switch it off.
The sender's address is read from the people table, never written in the code.
"""
import os
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb

from backend.api.deps import ApiError, conn
from backend.connectors.base import idempotency_key, raw_item_id
from backend.connectors.mailbox import message_items
from backend.db.events import new_event, publish

router = APIRouter()

ASSETS = Path(__file__).resolve().parent.parent / "demo_assets"
RECEIPTS = {
    "taxi": {"file": "taxi_800.jpg", "seller_tax_id": "9990031449", "subject": "Fwd: taxi na lotnisko",
             "body": "Hej, taksówka na lotnisko do klienta, 800 zł z mojej karty. Paragon w załączniku. Jan"},
    "bajt": {"file": "bajt_169.jpg", "seller_tax_id": "9990300006", "subject": "Fwd: mysz i podkładka",
             "body": "Hej, kupiłem mysz i podkładkę do biura, zapłaciłem swoją kartą. Paragon w załączniku. Jan"},
}
SENDERS = ("per_jan_testowy", "per_jan")
MAILBOX = "invoices@borsuk-labs.sample"


def enabled() -> bool:
    return os.environ.get("ORDO_DEMO_TRIGGER", "1") != "0"


def with_nonce(jpeg: bytes, nonce: str) -> bytes:
    """The same picture with a JPEG comment, so each send is a new file (the mailbox skips a file it already has)."""
    text = f"ordo-demo {nonce}".encode()
    return jpeg[:2] + b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text + jpeg[2:]


def _sender(c: psycopg.Connection, company: str) -> tuple[str, str]:
    for person in SENDERS:
        row = c.execute("select name, email from people where id = %s and company_id = %s and email is not null",
                        (person, company)).fetchone()
        if row:
            return row[0], row[1]
    raise ApiError(409, "conflict", "No employee with an e-mail address to send the demo receipt from")


def retire_previous(c: psycopg.Connection, company: str) -> list[str]:
    """Earlier demo receipts leave the pool, so the next one is not a duplicate of them."""
    tax_ids = [r["seller_tax_id"] for r in RECEIPTS.values()]
    rows = c.execute(
        """select id, doc from documents where company_id = %s and doc->>'status' <> 'rejected'
           and regexp_replace(coalesce(doc->'seller'->>'tax_id', ''), '[^0-9]', '', 'g') = any(%s)""",
        (company, tax_ids)).fetchall()
    retired = []
    for doc_id, doc in rows:
        c.execute("update documents set doc = %s where id = %s", (Jsonb({**doc, "status": "rejected"}), doc_id))
        suffix = doc_id.removeprefix("doc_")
        for rec_id, rec in c.execute(
                """select id, doc from recommendations where company_id = %s and doc->>'status' in ('new', 'seen')
                   and (doc::text like %s or doc::text like %s)""",
                (company, f"%{doc_id}%", f"%mat_{suffix}%")).fetchall():
            c.execute("update recommendations set doc = %s where id = %s", (Jsonb({**rec, "status": "superseded"}), rec_id))
            publish(c, new_event("recommendation.status_changed", company,
                                 {"recommendation_id": rec_id, "status": "superseded"}, producer="api"), commit=False)
        retired.append(doc_id)
    return retired


def send_receipt(c: psycopg.Connection, company: str, receipt: str) -> dict[str, Any]:
    spec = RECEIPTS[receipt]
    source = c.execute("select doc from sources where company_id = %s and doc->>'connector' = 'imap_mailbox' limit 1",
                       (company,)).fetchone()
    if source is None:
        raise ApiError(409, "conflict", f"{company} has no invoices mailbox")
    source = source[0]
    name, address = _sender(c, company)
    now = datetime.now(UTC)
    nonce = uuid.uuid4().hex[:12]

    mail = EmailMessage()
    mail["From"] = f"{name} <{address}>"
    mail["To"] = MAILBOX
    mail["Subject"] = spec["subject"]
    mail["Date"] = format_datetime(now)
    mail["Message-ID"] = f"<demo-{nonce}@ordo.sample>"
    mail.set_content(spec["body"])
    mail.add_attachment(with_nonce((ASSETS / spec["file"]).read_bytes(), nonce), maintype="image", subtype="jpeg",
                        filename=f"paragon_{nonce[:6]}.jpg")
    items = message_items(mail.as_bytes(), uid=int(now.timestamp()))

    retired = retire_previous(c, company)
    run_id = f"run_demo_{nonce}"
    fetched = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: dict[str, str] = {}
    for item in items:
        key = idempotency_key("imap", source["id"], item.external_id, item.sha256)
        rid = raw_item_id(key)
        ids[item.external_id] = rid
        doc = {"id": rid, "source_id": source["id"], "sync_run_id": run_id, "kind": item.kind,
               "external_id": item.external_id, "idempotency_key": key,
               "parent_raw_item_id": ids.get(item.parent_external_id) if item.parent_external_id else None,
               "received_at": item.received_at, "fetched_at": fetched, "content_type": item.content_type,
               "storage_uri": None, "sha256": item.sha256, "size_bytes": item.size_bytes,
               "metadata": {**item.metadata, "demo_trigger": True}, "payload": item.payload,
               "processing_status": "queued", "error": None}
        c.execute("insert into raw_items (id, company_id, doc) values (%s, %s, %s) on conflict do nothing",
                  (rid, company, Jsonb(doc)))
        if item.content is not None:
            c.execute("insert into raw_item_content (raw_item_id, content_type, bytes) values (%s, %s, %s) "
                      "on conflict do nothing", (rid, item.content_type, item.content))
        publish(c, new_event("raw_item.received", company, {"raw_item_id": rid, "kind": item.kind,
                                                            "source_id": source["id"]},
                             producer="connector", correlation_id=rid), commit=False)
    c.commit()
    return {"status": "sent", "from": name, "receipt": receipt, "raw_item_ids": list(ids.values()),
            "retired_documents": retired, "sent_at": fetched,
            "next": "The open app shows 'New receipt' and 'New to-do' in about 10-15 seconds."}


@router.api_route("/demo/receipt", methods=["GET", "POST"], include_in_schema=False)
def demo_receipt(company_id: str = Query("co_borsuk"), receipt: str = Query("taxi"),
                 c: psycopg.Connection = Depends(conn)):
    if not enabled():
        raise ApiError(404, "not_found", "The demo trigger is off")
    if receipt not in RECEIPTS:
        raise ApiError(422, "invalid_request", f"receipt must be one of {', '.join(RECEIPTS)}")
    return send_receipt(c, company_id, receipt)
