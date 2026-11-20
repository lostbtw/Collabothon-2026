"""The pipeline process's handlers, end to end on an in-memory store and event bus (no Postgres needed).
Run from the repo root:  python -m unittest discover -s backend/pipeline/tests -t .
"""
import copy
import unittest
from pathlib import Path

from backend.pipeline.handlers import HANDLERS, Context
from backend.pipeline.normalise.fx import StandInRates
from backend.pipeline.tests.schema_check import fixture, schema_errors

XML = (Path(__file__).parent / "data" / "fa3_hosting_sample.xml").read_bytes()
COMPANY = "co_borsuk"
PEOPLE = [{"person_id": "per_jan", "name": "Jan Kowalski (SAMPLE)", "email": "jan@borsuk-labs.sample", "role": "employee"},
          {"person_id": "per_tomek", "name": "Tomasz Borsuk (SAMPLE)", "email": "owner@borsuk-labs.sample",
           "role": "owner"}]
FILTERS = {"transaction": ("account_id", "external_id", "match_status"), "document": ("status", "direction"),
           "match": ("document_id", "match_type", "status")}


class MemoryStore:
    """Same interface and idempotency as backend/db/store.py, in memory."""

    def __init__(self):
        self.rows: dict[str, dict[str, tuple[str | None, dict]]] = {}

    def add(self, entity, doc, *, company_id=None):
        table = self.rows.setdefault(entity, {})
        if doc["id"] in table:
            return False
        if entity == "transaction" and any(d["account_id"] == doc["account_id"] and d["external_id"] == doc["external_id"]
                                           for _, d in table.values()):
            return False
        if entity == "document" and any(d["raw_item_ids"][:1] == doc["raw_item_ids"][:1] for _, d in table.values()):
            return False
        table[doc["id"]] = (company_id or doc.get("company_id"), copy.deepcopy(doc))
        return True

    def put(self, entity, doc, *, company_id=None):
        table = self.rows.setdefault(entity, {})
        old = table.get(doc["id"], (None, None))[0]
        table[doc["id"]] = (company_id or doc.get("company_id") or old, copy.deepcopy(doc))

    def get(self, entity, id):
        row = self.rows.get(entity, {}).get(id)
        return copy.deepcopy(row[1]) if row else None

    def company_of(self, entity, id):
        row = self.rows.get(entity, {}).get(id)
        return row[0] if row else None

    def list(self, entity, *, company_id=None, limit=None, **where):
        out = []
        for company, doc in self.rows.get(entity, {}).values():
            if company_id is not None and company != company_id:
                continue
            ok = True
            for column, value in where.items():
                have = doc.get(column)
                ok = ok and (have in value if isinstance(value, (list, tuple, set)) else have == value)
            if ok:
                out.append(copy.deepcopy(doc))
        return out


class Pipeline:
    """Store + event bus: published events are delivered to the pipeline's own handlers, like the outbox."""

    def __init__(self):
        self.store = MemoryStore()
        self.events: list[dict] = []
        self.queue: list[dict] = []
        for account in fixture("account"):
            self.store.add("account", account, company_id=account["company_id"])
        self.ctx = Context(store=self.store, publish=self.publish,
                           company=lambda c: {"id": c, "tax_id": "9990000014", "as_of_date": "2026-11-21"},
                           people=lambda c: PEOPLE, raw_bytes=lambda raw: XML if raw["kind"] == "ksef_invoice_xml" else None,
                           rates=StandInRates(), now=lambda: "2026-11-21T10:15:00Z")
        self.n = 0

    def publish(self, type_, company, payload, correlation=None, causation=None):
        self.n += 1
        event = {"id": f"evt_{self.n}", "type": type_, "company_id": company, "payload": payload,
                 "correlation_id": correlation, "causation_id": causation, "occurred_at": "2026-11-21T10:15:00Z"}
        self.events.append(event)
        self.queue.append(event)

    def run(self):
        while self.queue:
            event = self.queue.pop(0)
            for consumer in ("normaliser", "matcher"):
                for handler in HANDLERS[consumer].get(event["type"], []):
                    handler(self.ctx, event)

    def receive_raw(self, raw):
        self.store.add("raw_item", raw, company_id=COMPANY)
        self.publish("raw_item.received", COMPANY, {"raw_item_id": raw["id"], "kind": raw["kind"],
                                                    "source_id": raw["source_id"]}, raw["id"])
        self.run()

    def extracted(self, doc):
        """What role 1's extractor does: store the Document and announce it."""
        self.store.add("document", doc, company_id=COMPANY)
        self.publish("document.extracted", COMPANY, {"document_id": doc["id"]}, doc["raw_item_ids"][0])
        self.run()

    def types(self):
        return [e["type"] for e in self.events]


RAW = {r["id"]: r for r in fixture("raw_item")}
DOCS = {d["id"]: d for d in fixture("document")}


def ksef_raw(id_="raw_ksef0417"):
    return {"id": id_, "source_id": "src_ksef", "sync_run_id": "run_1", "kind": "ksef_invoice_xml",
            "external_id": id_, "idempotency_key": "a" * 63 + id_[-1], "fetched_at": "2026-11-05T09:00:00Z",
            "processing_status": "queued", "metadata": {}, "payload": None}


class HeroFlow(unittest.TestCase):
    def setUp(self):
        self.p = Pipeline()
        self.p.store.add("raw_item", RAW["raw_mail412"], company_id=COMPANY)
        self.p.store.add("raw_item", RAW["raw_mail412a1"], company_id=COMPANY)
        doc = copy.deepcopy(DOCS["doc_rcpt412"])
        doc["submitted_by"] = None  # who paid must come from the forwarding address, not the extractor
        self.p.extracted(doc)
        self.match = self.p.store.list("match", document_id="doc_rcpt412")[0]

    def test_receipt_becomes_jans_reimbursement(self):
        self.assertEqual(self.p.types(), ["document.extracted", "match.suggested"])
        self.assertEqual(schema_errors(self.match, "match"), [])
        self.assertEqual((self.match["paid_by"], self.match["score"]), ("employee_private", 0.86))
        self.assertEqual(self.match["consequences"]["reimbursement_owed"], {"amount": "1299.00", "currency": "PLN"})
        self.assertEqual(self.p.store.company_of("match", self.match["id"]), COMPANY)
        self.assertEqual(self.p.events[-1]["correlation_id"], "raw_mail412a1")

    def test_role_5_turns_it_into_the_pay_jan_back_card(self):
        try:
            from backend.agents.ingestion import recommendation_for_match
        except ImportError as exc:  # role 5's dependencies (psycopg, fastapi) are installed in CI, maybe not here
            self.skipTest(f"role 5 code not importable here: {exc}")
        doc = self.p.store.get("document", "doc_rcpt412")
        rec = recommendation_for_match(self.p.store, COMPANY, self.match, doc, "2026-11-21T10:15:00Z")
        self.assertEqual(rec["type"], "reimburse_employee")
        self.assertTrue(rec["title"].startswith("Pay Jan back 1,299.00"), rec["title"])
        self.assertEqual(schema_errors(rec, "recommendation"), [])


class BankLines(unittest.TestCase):
    def test_bank_line_becomes_transaction_then_pays_pixelboard(self):
        p = Pipeline()
        raw = copy.deepcopy(RAW["raw_bank731"])
        raw["payload"].update(valueDate="2026-11-19", proprietaryBankTransactionCode="CARD_PAYMENT")
        p.receive_raw(raw)
        [txn] = p.store.list("transaction")
        self.assertEqual(schema_errors(txn, "transaction"), [])
        self.assertEqual(p.store.get("raw_item", "raw_bank731")["processing_status"], "processed")
        p.extracted(copy.deepcopy(DOCS["doc_pixel11"]))
        [match] = p.store.list("match", document_id="doc_pixel11")
        self.assertEqual((match["match_type"], match["transaction_id"], match["status"]),
                         ("document_transaction", txn["id"], "suggested"))
        self.assertEqual(p.store.get("transaction", txn["id"])["match_status"], "suggested")

    def test_same_bank_line_twice_is_one_transaction(self):
        p = Pipeline()
        p.receive_raw(copy.deepcopy(RAW["raw_bank731"]))
        p.publish("raw_item.received", COMPANY, {"raw_item_id": "raw_bank731"}, "raw_bank731")
        p.run()
        self.assertEqual(len(p.store.list("transaction")), 1)
        self.assertEqual(p.types().count("transaction.ingested"), 1)

    def test_card_line_arriving_after_the_receipt(self):
        p = Pipeline()
        doc = copy.deepcopy(DOCS["doc_rcpt412"])
        doc["payment"]["card_last4"] = "4417"  # paid with the company card
        p.extracted(doc)
        first = p.store.list("match", document_id="doc_rcpt412")[0]
        self.assertEqual(first["match_type"], "document_no_transaction")
        line = copy.deepcopy(RAW["raw_bank731"])
        line.update(id="raw_bank800", external_id="E000000800", idempotency_key="b" * 64)
        line["payload"].update(entryReference="E000000800", bookingDate="2026-11-21",
                               transactionAmount={"amount": "-1299.00", "currency": "PLN"},
                               creditorName="ELEKTROMARKT POLSKA", proprietaryBankTransactionCode="CARD_PAYMENT",
                               remittanceInformationUnstructured="ELEKTROMARKT POLSKA KARTA *4417")
        p.receive_raw(line)
        [match] = p.store.list("match", document_id="doc_rcpt412")
        self.assertEqual((match["id"], match["match_type"], match["paid_by"]),
                         (first["id"], "document_transaction", "company_account"))

    def test_unreadable_line_is_marked_failed(self):
        p = Pipeline()
        raw = copy.deepcopy(RAW["raw_bank731"])
        raw["payload"]["transactionAmount"] = {"amount": "-10.00", "currency": "CHF"}  # no rate in the reference
        p.receive_raw(raw)
        stored = p.store.get("raw_item", "raw_bank731")
        self.assertEqual((stored["processing_status"], stored["error"]["code"]), ("failed", "normalise_failed"))
        self.assertEqual(p.store.list("transaction"), [])


class Duplicates(unittest.TestCase):
    def test_xml_first_then_pdf_copy_is_a_duplicate(self):
        p = Pipeline()
        p.receive_raw(ksef_raw())
        [xml_doc] = p.store.list("document")
        self.assertEqual(xml_doc["channel"], "ksef")
        pdf = copy.deepcopy(xml_doc)
        pdf.update(id="doc_mail0417", channel="email", raw_item_ids=["raw_mail0417a1"],
                   extraction={**xml_doc["extraction"], "method": "docling_llm"})
        p.extracted(pdf)
        self.assertEqual(p.store.get("document", "doc_mail0417")["duplicate_of"], xml_doc["id"])
        self.assertIn("document.duplicate_detected", p.types())
        self.assertEqual(p.store.list("match", document_id="doc_mail0417"), [])
        self.assertEqual(len(p.store.list("match", document_id=xml_doc["id"])), 1)

    def test_better_copy_later_takes_over_the_match(self):
        p = Pipeline()
        p.receive_raw(ksef_raw())
        xml_doc = p.store.list("document")[0]
        # start again with the PDF arriving first
        p = Pipeline()
        pdf = copy.deepcopy(xml_doc)
        pdf.update(id="doc_mail0417", channel="email", raw_item_ids=["raw_mail0417a1"],
                   extraction={**xml_doc["extraction"], "method": "docling_llm"})
        p.extracted(pdf)
        self.assertEqual(p.store.list("match", document_id="doc_mail0417")[0]["status"], "suggested")
        p.receive_raw(ksef_raw())
        self.assertEqual(p.store.list("match", document_id="doc_mail0417")[0]["status"], "rejected")
        self.assertEqual(p.store.list("match", document_id=xml_doc["id"])[0]["status"], "suggested")


class Decisions(unittest.TestCase):
    def test_rejected_match_frees_the_bank_line_and_owner_decision_sticks(self):
        p = Pipeline()
        raw = copy.deepcopy(RAW["raw_bank731"])
        raw["payload"].update(valueDate="2026-11-19", proprietaryBankTransactionCode="CARD_PAYMENT")
        p.receive_raw(raw)
        p.extracted(copy.deepcopy(DOCS["doc_pixel11"]))
        [match] = p.store.list("match", document_id="doc_pixel11")
        decided = {**match, "status": "rejected", "decided_at": "2026-11-21T11:00:00Z",
                   "decided_by": {"role": "owner", "person_id": "per_tomek", "name": None, "email": None}}
        p.store.put("match", decided)
        p.publish("match.decided", COMPANY, {"match_id": match["id"], "status": "rejected", "approval_id": "apr_1"})
        p.run()
        self.assertEqual(p.store.get("transaction", match["transaction_id"])["match_status"], "unmatched")
        p.publish("document.extracted", COMPANY, {"document_id": "doc_pixel11"})  # e.g. after a correction
        p.run()
        self.assertEqual(p.store.get("match", match["id"])["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
