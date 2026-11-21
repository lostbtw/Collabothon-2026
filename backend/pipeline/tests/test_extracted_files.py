"""Photos and PDFs from the extractor worker into the matcher: dedupe, match and who paid on `document.extracted`."""
import copy
import unittest
from datetime import date

from backend.pipeline.normalise.fx import StandInRates
from backend.pipeline.tests.schema_check import schema_errors
from backend.pipeline.tests.test_pipeline_handlers import COMPANY, RAW, Pipeline

try:
    from backend.pipeline.extract.document import build_document
    from backend.pipeline.extract.worker import build
except ImportError:
    build = None

BORSUK = {"id": COMPANY, "tax_id": "9990000014", "base_currency": "PLN"}
JAN = {"person_id": "per_jan", "name": "Jan Kowalski (SAMPLE)", "email": "jan@borsuk-labs.sample", "role": "employee"}
HERO = {
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


def worker_document(raw: dict, submitted_by: dict | None) -> dict:
    fields = build_document(copy.deepcopy(HERO), model="gpt-oss-20b", today=date(2026, 11, 21))
    return build(raw, fields, BORSUK, submitted_by=submitted_by, rates=StandInRates(),
                 created_at="2026-11-21T10:14:52Z")


@unittest.skipIf(build is None, "role 1's extractor worker needs httpx and psycopg")
class EmailedPhotoOfTheHeroReceipt(unittest.TestCase):
    def setUp(self):
        self.p = Pipeline()
        self.p.store.add("raw_item", RAW["raw_mail412"], company_id=COMPANY)
        self.p.store.add("raw_item", RAW["raw_mail412a1"], company_id=COMPANY)
        self.doc = worker_document(RAW["raw_mail412a1"], JAN)
        self.p.extracted(self.doc)

    def test_worker_document_is_whole(self):
        self.assertEqual(schema_errors(self.doc, "document"), [])
        self.assertEqual((self.doc["channel"], self.doc["direction"]), ("photo", "purchase"))

    def test_ends_as_jans_reimbursement_like_mat_412(self):
        self.assertEqual(self.p.types(), ["document.extracted", "match.suggested"])
        [match] = self.p.store.list("match", document_id=self.doc["id"])
        c = match["consequences"]
        self.assertEqual((match["paid_by"], match["payer"]["person_id"], match["status"]),
                         ("employee_private", "per_jan", "suggested"))
        self.assertEqual((c["reimbursement_owed"], c["vat_lost"], c["rule_ids"]),
                         ({"amount": "1299.00", "currency": "PLN"}, {"amount": "242.90", "currency": "PLN"},
                          ["PL-VAT-01", "PL-REIMB-01"]))
        self.assertEqual(schema_errors(match, "match"), [])

    def test_the_raw_item_is_left_to_the_extractor_worker(self):
        self.p.publish("raw_item.received", COMPANY, {"raw_item_id": "raw_mail412a1"}, "raw_mail412a1")
        self.p.run()
        self.assertEqual(self.p.types().count("document.extracted"), 1)
        self.assertEqual(self.p.store.get("raw_item", "raw_mail412a1")["processing_status"],
                         RAW["raw_mail412a1"]["processing_status"])


@unittest.skipIf(build is None, "role 1's extractor worker needs httpx and psycopg")
class UploadFromNobodyKnown(unittest.TestCase):
    def test_a_paid_receipt_becomes_the_question_at_once(self):
        p = Pipeline()
        raw = copy.deepcopy(RAW["raw_mail412a1"])
        raw.update(id="raw_up1", kind="upload", source_id="src_upload", parent_raw_item_id=None,
                   metadata={"filename": "x.jpg", "submitted_by": None})
        p.store.add("raw_item", raw, company_id=COMPANY)
        p.extracted(worker_document(raw, None))
        [match] = p.store.list("match", document_id="doc_up1")
        self.assertEqual((match["match_type"], match["paid_by"]), ("document_no_transaction", "unknown"))


if __name__ == "__main__":
    unittest.main()
