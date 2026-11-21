import pytest

from backend import tracing
from backend.db.events import new_event, publish
from backend.db.fixtures import read
from backend.db.store import Store
from backend.pipeline.extract import ExtractionError
from backend.pipeline.extract.main import process_pending
from backend.pipeline.extract.tests.test_extract_pipeline import HERO_MARKDOWN, FakeModel, extract
from backend.pipeline.extract.tests.test_extract_worker import FakeExtract, api, upload  # noqa: F401


def test_an_extraction_stores_the_id_of_the_trace_it_ran_in(traced):
    document = extract()

    assert document["extraction"]["trace_id"] == "tr-test"
    assert [(name, depth) for name, depth, _ in traced.spans] == [
        ("extract_document", 0), ("docling.convert", 1), ("build_document", 1)]


def test_the_trace_records_the_file_without_its_bytes_and_what_docling_and_the_checks_produced(traced):
    document = extract()

    inputs = traced.spans[0][2]
    assert inputs["content_type"] == "image/jpeg"
    assert set(inputs) == {"content_type", "bytes", "sha256"}
    assert traced.outputs["docling.convert"]["markdown"] == HERO_MARKDOWN
    assert traced.outputs["build_document"]["status"] == document["status"]
    assert traced.outputs["extract_document"]["gross"] == document["totals"]["gross"]


def test_a_failed_model_call_leaves_the_trace_without_a_build_step(traced):
    with pytest.raises(ExtractionError):
        extract(model_fake=FakeModel(error=RuntimeError("model down")))

    assert [name for name, _, _ in traced.spans] == ["extract_document", "docling.convert"]


def test_with_tracing_off_the_document_has_no_trace_id(monkeypatch):
    monkeypatch.setattr(tracing, "_enabled", False)

    assert extract()["extraction"]["trace_id"] is None


def test_an_extracted_upload_is_one_trace_tagged_with_its_item_company_and_document(api, db, traced):
    raw = upload(api)

    process_pending(db, FakeExtract())

    assert [(name, depth) for name, depth, _ in traced.spans] == [("raw_item.extract", 0)]
    document = Store(db).list("document", first_raw_item_id=raw["id"])[0]
    assert traced.tags == {"raw_item_id": raw["id"], "company_id": "co_borsuk", "kind": "upload",
                           "document_id": document["id"], "status": document["status"]}
    assert traced.outputs["raw_item.extract"]["document_id"] == document["id"]


def test_items_the_extractor_does_not_read_leave_no_trace(api, db, traced):
    store = Store(db)
    line = next(r for r in read("raw_item") if r["kind"] == "bank_transaction")
    store.add("raw_item", line, company_id="co_borsuk")
    publish(db, new_event("raw_item.received", "co_borsuk", {"raw_item_id": line["id"], "kind": line["kind"],
                                                             "source_id": line["source_id"]}, producer="connector"))
    upload(api, data=b"just text", content_type="text/plain")

    process_pending(db, FakeExtract())

    assert traced.spans == []
