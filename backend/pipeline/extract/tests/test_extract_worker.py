import copy
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.contract import entity_errors
from backend.db.events import new_event, publish
from backend.db.fixtures import read
from backend.db.seed import seed
from backend.db.store import Store
from backend.pipeline.extract import ExtractionError
from backend.pipeline.extract.document import build_document
from backend.pipeline.extract.main import process_pending
from backend.pipeline.extract.tests.test_extract_document import HERO, USD_INVOICE
from backend.pipeline.extract.worker import build
from backend.pipeline.normalise.fx import StandInRates

JPEG = b"\xff\xd8\xff\xe0 SAMPLE receipt photo"
BORSUK = {"id": "co_borsuk", "tax_id": "9990000014", "base_currency": "PLN"}
UPLOAD = {"id": "raw_up1", "kind": "upload", "content_type": "image/jpeg"}


def fields(answer=HERO):
    return build_document(copy.deepcopy(answer), model="gpt-oss-20b", today=date(2026, 11, 21))


class FakeExtract:
    def __init__(self, answer=HERO, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def __call__(self, data, content_type):
        self.calls.append((data, content_type))
        if self.error:
            raise self.error
        return fields(self.answer)


@pytest.fixture
def api(db, db_url):
    seed(db)
    store = Store(db)
    for account in read("account"):
        store.add("account", account, company_id=account["company_id"])
    with TestClient(create_app(database_url=db_url)) as client:
        yield client


def upload(api, data=JPEG, content_type="image/jpeg", **form):
    response = api.post("/api/v1/uploads", params={"company_id": "co_borsuk"},
                        files={"file": ("IMG_2041.jpg", data, content_type)}, data=form)
    assert response.status_code == 201, response.text
    return response.json()


def delivery(db, raw_id):
    return db.execute(
        """select d.status, d.attempts from outbox_delivery d join outbox o on o.id = d.event_id
           where d.consumer = 'extractor' and o.payload->>'raw_item_id' = %s""", (raw_id,)).fetchone()


def events(db, type_):
    return [row[0] for row in db.execute("select payload from outbox where type = %s order by seq", (type_,))]


def test_uploaded_photo_becomes_a_document_and_a_suggested_match(api, db, monkeypatch):
    raw = upload(api, submitted_by="per_jan")
    extract = FakeExtract()

    assert process_pending(db, extract) == 1

    assert extract.calls == [(JPEG, "image/jpeg")]
    [doc] = api.get("/api/v1/documents", params={"company_id": "co_borsuk", "q": "ElektroMarkt"}).json()["items"]
    assert entity_errors("document", doc) == []
    assert doc["raw_item_ids"] == [raw["id"]]
    assert doc["channel"] == "upload"
    assert doc["direction"] == "purchase"
    assert doc["submitted_by"] == {"person_id": "per_jan", "name": "Jan Kowalski (SAMPLE)",
                                   "email": "jan@borsuk-labs.sample", "role": "employee"}
    assert doc["payment"]["card_last4"] == "7730"
    assert doc["extraction"]["method"] == "docling_llm"
    assert doc["flags"] == ["buyer_not_company", "vat_not_deductible"]
    assert events(db, "document.extracted") == [
        {"document_id": doc["id"], "status": doc["status"], "gross": {"amount": "1299.00", "currency": "PLN"},
         "seller": "ElektroMarkt Polska S.A. (SAMPLE)", "flags": ["buyer_not_company", "vat_not_deductible"]}]
    assert api.get(f"/api/v1/raw-items/{raw['id']}").json()["processing_status"] == "processed"
    assert delivery(db, raw["id"]) == ("done", 1)

    from backend.pipeline import main as pipeline
    monkeypatch.setattr(pipeline, "_CHOOSE", None)
    pipeline.process_pending(db, "matcher")

    [suggested] = events(db, "match.suggested")
    assert suggested["document_id"] == doc["id"]
    assert suggested["paid_by"] == "employee_private"


def test_a_repeated_delivery_does_not_read_the_file_again(api, db):
    raw = upload(api)
    extract = FakeExtract()
    process_pending(db, extract)
    publish(db, new_event("raw_item.received", "co_borsuk", {"raw_item_id": raw["id"], "kind": "upload",
                                                             "source_id": "src_upload"}, producer="api"))

    assert process_pending(db, extract) == 1

    assert len(extract.calls) == 1
    assert len(events(db, "document.extracted")) == 1


def test_a_file_that_is_not_a_photo_or_pdf_is_ignored(api, db):
    raw = upload(api, data=b"just text", content_type="text/plain")
    extract = FakeExtract()

    process_pending(db, extract)

    item = api.get(f"/api/v1/raw-items/{raw['id']}").json()
    assert item["processing_status"] == "ignored"
    assert item["error"]["code"] == "unsupported_content_type"
    assert extract.calls == []
    assert events(db, "document.extracted") == []


def test_bank_lines_are_left_to_the_normaliser(api, db):
    store = Store(db)
    line = next(r for r in read("raw_item") if r["kind"] == "bank_transaction")
    store.add("raw_item", line, company_id="co_borsuk")
    publish(db, new_event("raw_item.received", "co_borsuk", {"raw_item_id": line["id"], "kind": line["kind"],
                                                             "source_id": line["source_id"]}, producer="connector"))
    extract = FakeExtract()

    assert process_pending(db, extract) == 1

    assert extract.calls == []
    assert store.get("raw_item", line["id"])["processing_status"] == line["processing_status"]


def test_a_failing_extraction_is_retried_then_dead_and_the_item_failed(api, db):
    raw = upload(api)
    extract = FakeExtract(error=ExtractionError("docling-serve unreachable: ConnectError"))

    for _ in range(3):
        process_pending(db, extract, retry_after_seconds=0)

    assert delivery(db, raw["id"]) == ("dead", 3)
    item = api.get(f"/api/v1/raw-items/{raw['id']}").json()
    assert item["processing_status"] == "failed"
    assert item["error"]["code"] == "extraction_failed"
    assert "docling-serve unreachable" in item["error"]["message"]


def test_an_attachment_forwarded_by_an_employee_names_them(api, db):
    store = Store(db)
    mail = {"id": "raw_mail9", "source_id": "src_mail", "sync_run_id": "run_9", "kind": "email",
            "external_id": "<9@mail.example.test>", "idempotency_key": "k-mail9", "fetched_at": "2026-11-21T10:00:00Z",
            "processing_status": "queued", "metadata": {"from": "Jan@Borsuk-Labs.sample"}}
    attachment = {**mail, "id": "raw_mail9a1", "kind": "email_attachment", "external_id": "<9@mail.example.test>#1",
                  "idempotency_key": "k-mail9a1", "parent_raw_item_id": "raw_mail9", "content_type": "image/jpeg",
                  "metadata": {"filename": "IMG_1.jpg"}}
    store.add("raw_item", mail, company_id="co_borsuk")
    store.add("raw_item", attachment, company_id="co_borsuk")
    db.execute("insert into raw_item_content (raw_item_id, content_type, bytes) values ('raw_mail9a1', 'image/jpeg', %s)",
               (JPEG,))
    db.commit()
    publish(db, new_event("raw_item.received", "co_borsuk", {"raw_item_id": "raw_mail9a1", "kind": "email_attachment",
                                                             "source_id": "src_mail"}, producer="connector-mail",
                          correlation_id="raw_mail9"))

    process_pending(db, FakeExtract())

    doc = store.get("document", "doc_mail9a1")
    assert doc["channel"] == "photo"
    assert doc["submitted_by"]["person_id"] == "per_jan"
    assert db.execute("select correlation_id from outbox where type = 'document.extracted'").fetchone() == ("raw_mail9",)


def test_our_own_tax_id_as_seller_makes_a_sale():
    answer = copy.deepcopy(USD_INVOICE)
    answer["seller"], answer["buyer"] = answer["buyer"], answer["seller"]

    doc = build(UPLOAD, fields(answer), BORSUK, submitted_by=None, rates=StandInRates(), created_at="2026-11-21T10:00:00Z")

    assert doc["direction"] == "sale"
    assert doc["buyer"]["is_company"] is False


def test_a_foreign_invoice_gets_its_pln_amount_at_the_nbp_rate():
    doc = build({**UPLOAD, "content_type": "application/pdf"}, fields(USD_INVOICE), BORSUK, submitted_by=None,
                rates=StandInRates(), created_at="2026-11-21T10:00:00Z")

    assert entity_errors("document", doc) == []
    assert doc["totals"]["fx"]["source"].startswith("NBP")
    assert doc["totals"]["gross_base"]["currency"] == "PLN"
    assert doc["buyer"]["is_company"] is True
    assert "foreign_currency" in doc["flags"]
    assert doc["channel"] == "upload"
