"""Duplicate detection and golden record."""
import copy
import unittest
from pathlib import Path

from backend.pipeline.dedupe import (add_document, deduplicate, drop_identical_files, duplicate_detected_payload,
                                     duplicate_reason)
from backend.pipeline.normalise.fa3 import parse_fa3
from backend.pipeline.tests import generated_world as world
from backend.pipeline.tests.schema_check import fixture, schema_errors

XML = (Path(__file__).parent / "data" / "fa3_hosting_sample.xml").read_text(encoding="utf-8")
BORSUK = {"id": "co_borsuk", "tax_id": "9990000014"}


def three_copies():
    xml = parse_fa3(XML, {"id": "raw_ksef0417", "fetched_at": "2026-11-05T09:00:00Z"}, BORSUK)
    pdf = copy.deepcopy(xml)
    pdf.update(id="doc_mail0417", channel="email", raw_item_ids=["raw_mail0417a1"], created_at="2026-11-05T08:10:00Z",
               extraction={**xml["extraction"], "method": "docling_llm", "confidence": 0.95})
    pdf["seller"] = {**pdf["seller"], "name": "CHMURA HOSTING SP Z O O", "tax_id": "999-000-01-03"}
    photo = copy.deepcopy(pdf)
    photo.update(id="doc_photo0417", channel="photo", number=None, raw_item_ids=["raw_tg0417"],
                 created_at="2026-11-05T08:05:00Z", extraction={**pdf["extraction"], "method": "llm_vision"})
    photo["seller"] = {**photo["seller"], "name": "Chmura Hostng (SAMPLE)", "tax_id": None}
    return xml, pdf, photo


class ThreeChannels(unittest.TestCase):
    def test_one_golden_record_and_two_duplicates(self):
        xml, pdf, photo = three_copies()
        result = deduplicate([photo, pdf, xml])
        self.assertEqual(result["clusters"], [["doc_ksef0417", "doc_mail0417", "doc_photo0417"]])
        by_id = {d["id"]: d for d in result["documents"]}
        self.assertEqual(by_id["doc_ksef0417"]["status"], "extracted")
        for dup in ("doc_mail0417", "doc_photo0417"):
            self.assertEqual((by_id[dup]["status"], by_id[dup]["duplicate_of"]), ("duplicate", "doc_ksef0417"))
        reasons = {m["document_id"]: m["reason"] for m in result["merges"]}
        self.assertTrue(reasons["doc_mail0417"].startswith("D1: same invoice number FV/11/2026/0417"))
        self.assertTrue(reasons["doc_photo0417"].startswith("D2:"))
        self.assertTrue(all(m["control_level"] == "analysed_autonomously" for m in result["merges"]))
        for doc in result["documents"]:
            self.assertEqual(schema_errors(doc, "document"), [], doc["id"])

    def test_live_arrival_photo_then_pdf_then_xml(self):
        xml, pdf, photo = three_copies()
        first = add_document(photo, [])
        self.assertEqual((first["merges"], first["golden_changed"]), ([], None))
        second = add_document(pdf, [photo])
        self.assertEqual(second["golden_changed"], "doc_photo0417")
        state = {d["id"]: d for d in [photo] + second["documents"]}
        third = add_document(xml, list(state.values()))
        self.assertEqual(third["golden_changed"], "doc_mail0417")
        state.update({d["id"]: d for d in third["documents"]})
        self.assertEqual(state["doc_ksef0417"]["status"], "extracted")
        self.assertEqual({state[i]["duplicate_of"] for i in ("doc_mail0417", "doc_photo0417")}, {"doc_ksef0417"})

    def test_event_payload(self):
        merge = deduplicate(list(three_copies()))["merges"][0]
        self.assertEqual(set(duplicate_detected_payload(merge)), {"document_id", "duplicate_of", "reason"})


class UploadedPhotoOfTheHeroReceipt(unittest.TestCase):
    def setUp(self):
        self.photo = copy.deepcopy(next(d for d in fixture("document") if d["id"] == "doc_rcpt412"))
        self.upload = copy.deepcopy(self.photo)
        self.upload.update(id="doc_up412", channel="upload", number=None, raw_item_ids=["raw_up412"],
                           created_at="2026-11-21T09:08:50Z", status="needs_review",
                           extraction={**self.photo["extraction"], "confidence": 0.6})

    def test_a_worse_upload_does_not_take_over_the_photo(self):
        result = add_document(self.upload, [self.photo])
        self.assertIsNone(result["golden_changed"])
        [merge] = result["merges"]
        self.assertEqual((merge["document_id"], merge["duplicate_of"]), ("doc_up412", "doc_rcpt412"))

    def test_between_two_phone_copies_the_more_confident_reading_wins(self):
        self.upload["extraction"]["confidence"] = 0.98
        result = add_document(self.upload, [self.photo])
        self.assertEqual(result["golden_changed"], "doc_rcpt412")

    def test_an_emailed_pdf_still_outranks_an_upload(self):
        pdf = copy.deepcopy(self.upload)
        pdf.update(id="doc_pdf412", channel="email", raw_item_ids=["raw_pdf412"])
        pdf["extraction"]["confidence"] = 0.5
        self.assertEqual(deduplicate([self.upload, pdf])["clusters"], [["doc_pdf412", "doc_up412"]])


class NotDuplicates(unittest.TestCase):
    def test_two_monthly_invoices_with_different_numbers(self):
        xml, pdf, _ = three_copies()
        pdf["number"] = "FV/12/2026/0533"
        self.assertIsNone(duplicate_reason(xml, pdf))

    def test_same_number_from_different_sellers(self):
        xml, pdf, _ = three_copies()
        pdf["seller"] = {**pdf["seller"], "name": "Biuromax sp. z o.o. (SAMPLE)", "tax_id": "9990000149"}
        self.assertIsNone(duplicate_reason(xml, pdf))

    def test_photo_with_a_different_date(self):
        xml, _, photo = three_copies()
        photo["issue_date"] = "2026-11-06"
        self.assertIsNone(duplicate_reason(xml, photo))

    def test_other_company(self):
        xml, pdf, _ = three_copies()
        pdf["company_id"] = "co_other"
        self.assertIsNone(duplicate_reason(xml, pdf))


class IdenticalFiles(unittest.TestCase):
    def test_same_sha256_is_dropped_once(self):
        a, b = copy.deepcopy(fixture("raw_item")[1]), copy.deepcopy(fixture("raw_item")[1])
        b.update(id="raw_mail999a1", fetched_at="2026-11-21T11:00:00Z")
        kept, dropped = drop_identical_files([b, a])
        self.assertEqual(([k["id"] for k in kept], [d["id"] for d in dropped]), (["raw_mail412a1"], ["raw_mail999a1"]))


class GeneratedWorld(unittest.TestCase):
    def test_clusters_are_pure_and_complete(self):
        for seed in range(1, 6):
            copies = world.build_copies(seed)
            event_of = {d["id"]: e for d, e in copies}
            result = deduplicate([d for d, _ in copies])
            impure = [c for c in result["clusters"] if len({event_of[i] for i in c}) != 1]
            with self.subTest(seed=seed):
                self.assertEqual(impure, [], "every cluster is one purchase")
                self.assertEqual(len(result["clusters"]), len(set(event_of.values())), "one cluster per purchase")
                golden = {c[0] for c in result["clusters"]}
                self.assertEqual(golden, {f"doc_E{e}" for e in set(event_of.values())}, "best copy is golden")


if __name__ == "__main__":
    unittest.main()
