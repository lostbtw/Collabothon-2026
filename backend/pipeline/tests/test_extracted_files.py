"""Photos and PDFs through the pipeline (#25 with role 1's #17): RawItem -> role 1's real extract_document() (docling
and the model faked) -> whole Document -> dedupe, match, who paid. Run from the repo root:
    python -m unittest discover -s backend/pipeline/tests -t .
"""
import copy
import json
import unittest
from types import SimpleNamespace

from backend.pipeline.normalise.extracted import document_from_extraction, person_ref
from backend.pipeline.tests.schema_check import schema_errors
from backend.pipeline.tests.test_pipeline_handlers import COMPANY, PEOPLE, RAW, XML, Pipeline

try:
    import httpx

    from backend.pipeline.extract import extract_document
except ImportError as exc:  # role 1's dependencies (httpx, openai) are installed in CI, maybe not here
    extract_document, MISSING = None, str(exc)

JPEG, PDF = b"\xff\xd8\xff\xe0 SAMPLE photo", b"%PDF-1.7 SAMPLE"
HERO = {  # what gpt-oss answers for the hero receipt (same as role 1's test answer)
    "doc_type": "receipt", "number": "PARAGON 004512/11/2026", "issue_date": "2026-11-20", "sale_date": None,
    "due_date": None,
    "seller": {"name": "ElektroMarkt Polska S.A. (SAMPLE)", "tax_id": "9990000043", "country": "PL", "address": None},
    "buyer": {"name": None, "tax_id": None, "country": None, "address": None},
    "currency": "PLN", "gross": "1299.00", "net": None, "vat": "242.90",
    "vat_lines": [{"rate": "23", "vat": "242.90", "gross": "1299.00"}],
    "lines": [{"description": "Monitor 27 cali QHD (SAMPLE)", "quantity": 1, "unit_price": "1299.00", "net": None,
               "vat_rate": "23"}],
    "payment_method": "card", "card_last4": "7730", "bank_account": None, "confidence": 0.93,
    "field_confidence": {"gross": 0.99, "net": 0.5, "vat": 0.96, "issue_date": 0.95, "number": 0.9,
                         "seller_tax_id": 0.97, "buyer_tax_id": 0.9},
}
USD_INVOICE = {**HERO, "doc_type": "invoice", "number": "INV-2026-1107", "issue_date": "2026-11-07",
               "seller": {"name": "Cloudscale Inc. (SAMPLE)", "tax_id": "US-99-0000007", "country": "US",
                          "address": None},
               "buyer": {"name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "PL9990000014", "country": "PL",
                         "address": None},
               "currency": "USD", "gross": "480.00", "net": "480.00", "vat": "0.00",
               "vat_lines": [{"rate": "np I", "vat": "0.00", "gross": "480.00"}],
               "lines": [{"description": "Cloud hosting 11/2026 (SAMPLE)", "quantity": 1, "unit_price": "480.00",
                          "net": "480.00", "vat_rate": "np"}],
               "payment_method": "transfer", "card_last4": None}


def fake_extractor(answer: dict, calls: list | None = None):
    """Role 1's extract_document() with docling-serve and gpt-oss replaced by fakes."""
    def docling(request):
        return httpx.Response(200, json={"document": {"md_content": "SAMPLE document", "json_content": None},
                                         "status": "success", "errors": [], "processing_time": 1.0, "timings": {}})

    def create(**kwargs):
        message = SimpleNamespace(content=json.dumps(answer))
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def extract(data, content_type, today):
        if calls is not None:
            calls.append(content_type)
        client = httpx.Client(base_url="http://docling.test", transport=httpx.MockTransport(docling))
        from datetime import date
        return extract_document(data, content_type, today=date.fromisoformat(today), docling_client=client,
                                llm_client=llm)
    return extract


def pipeline(files: dict[str, bytes], extract) -> Pipeline:
    p = Pipeline()
    p.ctx.raw_bytes = lambda raw: files.get(raw["id"])
    p.ctx.extract = extract
    return p


def attachment(id_, content_type, sender="jan@borsuk-labs.sample", parent="raw_mail412"):
    raw = copy.deepcopy(RAW["raw_mail412a1"])
    raw.update(id=id_, content_type=content_type, parent_raw_item_id=parent, processing_status="queued",
               idempotency_key=(id_ * 64)[:64])
    raw["metadata"] = {"filename": "scan", "forwarded_by": sender} if sender else {"filename": "scan"}
    return raw


@unittest.skipIf(extract_document is None, "role 1's extractor needs httpx and openai")
class EmailedPhotoOfTheHeroReceipt(unittest.TestCase):
    def setUp(self):
        self.p = pipeline({"raw_mail412a1": JPEG}, fake_extractor(HERO))
        self.p.store.add("raw_item", RAW["raw_mail412"], company_id=COMPANY)
        raw = copy.deepcopy(RAW["raw_mail412a1"])
        raw["processing_status"] = "queued"
        self.p.receive_raw(raw)
        self.doc = self.p.store.get("document", "doc_mail412a1")

    def test_becomes_a_whole_document(self):
        self.assertEqual(schema_errors(self.doc, "document"), [])
        self.assertEqual((self.doc["channel"], self.doc["direction"], self.doc["raw_item_ids"], self.doc["company_id"]),
                         ("photo", "purchase", ["raw_mail412a1"], COMPANY))
        self.assertEqual(self.doc["submitted_by"]["person_id"], "per_jan")
        self.assertEqual(self.doc["totals"]["gross_base"], {"amount": "1299.00", "currency": "PLN"})
        self.assertEqual(self.doc["extraction"]["method"], "docling_llm")
        self.assertEqual(self.p.store.get("raw_item", "raw_mail412a1")["processing_status"], "processed")

    def test_ends_as_jans_reimbursement_like_mat_412(self):
        self.assertEqual(self.p.types(), ["raw_item.received", "document.extracted", "match.suggested"])
        [match] = self.p.store.list("match", document_id="doc_mail412a1")
        c = match["consequences"]
        self.assertEqual((match["paid_by"], match["payer"]["person_id"], match["status"]),
                         ("employee_private", "per_jan", "suggested"))
        self.assertEqual((c["reimbursement_owed"], c["vat_lost"], c["rule_ids"]),
                         ({"amount": "1299.00", "currency": "PLN"}, {"amount": "242.90", "currency": "PLN"},
                          ["PL-VAT-01", "PL-REIMB-01"]))
        self.assertEqual(schema_errors(match, "match"), [])
        self.assertEqual(self.p.events[-1]["correlation_id"], "raw_mail412a1")

    def test_the_same_raw_item_twice_is_one_document(self):
        self.p.publish("raw_item.received", COMPANY, {"raw_item_id": "raw_mail412a1"}, "raw_mail412a1")
        self.p.run()
        self.assertEqual(len(self.p.store.list("document")), 1)
        self.assertEqual(self.p.types().count("document.extracted"), 1)


@unittest.skipIf(extract_document is None, "role 1's extractor needs httpx and openai")
class OtherFiles(unittest.TestCase):
    def test_emailed_usd_pdf_gets_the_nbp_rate_of_the_previous_business_day(self):
        p = pipeline({"raw_inv1": PDF}, fake_extractor(USD_INVOICE))
        p.receive_raw(attachment("raw_inv1", "application/pdf", parent=None))
        doc = p.store.get("document", "doc_inv1")
        self.assertEqual(schema_errors(doc, "document"), [])
        self.assertEqual(doc["channel"], "email")
        self.assertEqual(doc["totals"]["gross"], {"amount": "480.00", "currency": "USD"})
        self.assertEqual(doc["totals"]["gross_base"]["currency"], "PLN")
        self.assertEqual((doc["totals"]["fx"]["rate_date"], doc["totals"]["fx"]["rule"]),
                         ("2026-11-06", "pl_tax_prev_business_day"))

    def test_extractor_down_twice_marks_the_raw_item_failed_and_retryable(self):
        calls = []

        def down(data, content_type, today):
            calls.append(content_type)
            raise RuntimeError("docling-serve unreachable")
        p = pipeline({"raw_ph1": JPEG}, down)
        p.receive_raw(attachment("raw_ph1", "image/jpeg"))
        raw = p.store.get("raw_item", "raw_ph1")
        self.assertEqual((raw["processing_status"], raw["error"]["code"], raw["error"]["retryable"]),
                         ("failed", "extraction_failed", True))
        self.assertEqual((len(calls), p.store.list("document")), (2, []))

    def test_upload_form_photo_from_an_unknown_person(self):
        p = pipeline({"raw_up1": JPEG}, fake_extractor(HERO))
        raw = attachment("raw_up1", "image/png", sender=None, parent=None)
        raw.update(kind="upload", source_id="src_upload", metadata={"filename": "x.png", "submitted_by": None})
        p.receive_raw(raw)
        doc = p.store.get("document", "doc_up1")
        self.assertEqual((doc["channel"], doc["submitted_by"]), ("upload", None))
        [match] = p.store.list("match", document_id="doc_up1")
        self.assertEqual(match["paid_by"], "unknown")


class NoModelNeeded(unittest.TestCase):
    def test_uploaded_fa3_xml_is_parsed_without_the_extractor(self):
        p = pipeline({"raw_up2": XML}, None)
        raw = attachment("raw_up2", "application/xml", sender=None, parent=None)
        raw.update(kind="upload", source_id="src_upload")
        p.receive_raw(raw)
        doc = p.store.get("document", "doc_up2")
        self.assertEqual((doc["extraction"]["method"], schema_errors(doc, "document")), ("xml_parse", []))

    def test_unreadable_file_types_and_missing_bytes_fail_for_good(self):
        p = pipeline({"raw_t1": b"hello"}, lambda *a: self.fail("no extractor call"))
        p.receive_raw(attachment("raw_t1", "text/plain"))
        p.receive_raw(attachment("raw_t2", "image/jpeg"))  # no bytes stored
        errors = [p.store.get("raw_item", r)["error"] for r in ("raw_t1", "raw_t2")]
        self.assertEqual([(e["code"], e["retryable"]) for e in errors],
                         [("unsupported_content_type", False), ("normalise_failed", False)])

    def test_no_extractor_configured(self):
        p = pipeline({"raw_t3": JPEG}, None)
        p.receive_raw(attachment("raw_t3", "image/jpeg"))
        self.assertEqual(p.store.get("raw_item", "raw_t3")["error"]["code"], "extraction_failed")

    def test_envelope_direction_and_sender(self):
        fields = {"seller": {"name": "Borsuk Labs (SAMPLE)", "tax_id": "PL 999-000-00-14"},
                  "totals": {"gross": {"amount": "100.00", "currency": "PLN"}},
                  "extraction": {"method": "docling_llm", "warnings": []}, "status": "extracted", "flags": []}
        raw = attachment("raw_s1", "application/pdf")
        doc = document_from_extraction(fields, raw, {"id": COMPANY, "tax_id": "9990000014"}, people=PEOPLE,
                                       sender="OWNER@borsuk-labs.sample")
        self.assertEqual((doc["direction"], doc["submitted_by"]["person_id"]), ("sale", "per_tomek"))
        self.assertEqual(person_ref("someone@else.sample", PEOPLE),
                         {"person_id": None, "name": None, "email": "someone@else.sample", "role": "unknown"})


if __name__ == "__main__":
    unittest.main()
