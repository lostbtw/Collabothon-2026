"""Missing documents and documents without a payment."""
import copy
import unittest

from backend.pipeline import handlers
from backend.pipeline.match import run_matching
from backend.pipeline.missing import line_status
from backend.pipeline.tests import generated_world as world
from backend.pipeline.tests.schema_check import fixture
from backend.pipeline.tests.test_pipeline_handlers import COMPANY, RAW, XML, Pipeline, ksef_raw

AS_OF = "2026-11-21"


def line(amount="-250.00", booked="2026-11-14", type_="card_payment", text="SKLEP SAMPLE", status="unmatched"):
    return {"id": "txn_x", "account_id": "acc_pln", "booking_date": booked, "match_status": status,
            "amount_base": {"amount": amount, "currency": "PLN"}, "transaction_type": type_,
            "counterparty_name_raw": text, "description": text, "category": None}


class BankLineRules(unittest.TestCase):
    def test_purchase_line_without_document(self):
        self.assertEqual(line_status(line(booked="2026-11-16"), AS_OF), "missing_document")  # 5 days: ask
        self.assertIsNone(line_status(line(booked="2026-11-18"), AS_OF))  # 3 days: the receipt may still come
        self.assertIsNone(line_status(line(booked="2026-09-01"), AS_OF))  # old history: not chased

    def test_lines_that_never_have_a_document(self):
        self.assertEqual(line_status(line(text="WYNAGRODZENIE 10/2026", type_="transfer_out"), AS_OF),
                         "no_document_needed")
        self.assertEqual(line_status(line(text="ZUS SKLADKI", type_="direct_debit"), AS_OF), "no_document_needed")
        self.assertEqual(line_status(line(type_="tax", text="URZAD SKARBOWY"), AS_OF), "no_document_needed")
        self.assertEqual(line_status(line(amount="1149.36", type_="card_settlement"), AS_OF), "no_document_needed")

    def test_left_alone(self):
        self.assertIsNone(line_status(line(amount="36900.00", type_="transfer_in"), AS_OF))  # waits for a sales invoice
        self.assertIsNone(line_status(line(status="suggested"), AS_OF))


def not_due_invoice_pipeline(due="2026-12-15"):
    p = Pipeline()
    p.ctx.raw_bytes = lambda raw: XML.replace(b"<Termin>2026-11-19</Termin>", f"<Termin>{due}</Termin>".encode())
    p.receive_raw(ksef_raw())
    return p


class DocumentsWithoutPayment(unittest.TestCase):
    def test_not_due_yet_is_a_payable_not_a_question(self):
        p = not_due_invoice_pipeline()
        self.assertEqual(p.store.list("match", document_id="doc_ksef0417"), [])
        self.assertNotIn("match.suggested", p.types())

    def test_asked_once_it_is_due(self):
        p = not_due_invoice_pipeline()
        p.ctx.company = lambda c: {"id": c, "tax_id": "9990000014", "as_of_date": "2026-12-16"}
        counts = handlers.sweep(p.ctx, COMPANY)
        self.assertEqual(counts["asked"], 1)
        [match] = p.store.list("match", document_id="doc_ksef0417")
        self.assertEqual((match["match_type"], match["paid_by"], match["status"]),
                         ("document_no_transaction", "unknown", "suggested"))
        self.assertLess(match["score"], 0.55)  # shown as "Which payment is this?"
        self.assertIn("match.suggested", p.types())
        self.assertEqual(handlers.sweep(p.ctx, COMPANY)["asked"], 0)  # asked once

    def test_the_transfer_pays_a_payable_that_was_not_due(self):
        p = not_due_invoice_pipeline()
        raw = copy.deepcopy(RAW["raw_bank731"])
        raw.update(id="raw_bank900", external_id="E000000900", idempotency_key="c" * 64)
        raw["payload"] = {"entryReference": "E000000900", "bookingDate": "2026-12-10", "valueDate": "2026-12-10",
                          "transactionAmount": {"amount": "-479.70", "currency": "PLN"},
                          "creditorName": "Chmura Hosting sp. z o.o.",
                          "creditorAccount": {"iban": "PL99999900000000000000000103"},
                          "remittanceInformationUnstructured": "Zaplata FV/11/2026/0417",
                          "proprietaryBankTransactionCode": "TRANSFER"}
        p.receive_raw(raw)
        [match] = p.store.list("match", document_id="doc_ksef0417")
        self.assertEqual((match["match_type"], match["transaction_id"]),
                         ("document_transaction", "txn_pln_E000000900"))


class LateReceipt(unittest.TestCase):
    def test_line_flagged_missing_still_matches_when_the_receipt_arrives(self):
        p = Pipeline()
        raw = copy.deepcopy(RAW["raw_bank731"])
        raw["payload"].update(valueDate="2026-11-12", bookingDate="2026-11-12",
                              proprietaryBankTransactionCode="CARD_PAYMENT")
        p.receive_raw(raw)
        self.assertEqual(handlers.sweep(p.ctx, COMPANY)["missing_document"], 1)
        self.assertEqual(p.store.get("transaction", "txn_pln_E000000731")["match_status"], "missing_document")
        doc = copy.deepcopy(next(d for d in fixture("document") if d["id"] == "doc_pixel11"))
        doc.update(issue_date="2026-11-11", sale_date="2026-11-11")
        doc["totals"]["fx"]["rate_date"] = "2026-11-10"
        p.extracted(doc)
        [match] = p.store.list("match", document_id="doc_pixel11")
        self.assertEqual(match["transaction_id"], "txn_pln_E000000731")
        self.assertEqual(p.store.get("transaction", "txn_pln_E000000731")["match_status"], "suggested")


class GeneratedWorld(unittest.TestCase):
    def test_missing_documents_equal_ground_truth(self):
        for seed in range(1, 6):
            docs, bank, senders, truth = world.build(seed)
            results = run_matching(docs, bank, company=world.COMPANY, people=world.PEOPLE, accounts=world.ACCOUNTS,
                                   now="2026-11-07T00:00:00Z", senders=senders)
            paid = {r["match"]["transaction_id"] for r in results if r["match"]["transaction_id"]}
            statuses = {t["id"]: line_status(t, "2026-11-07", lookback_days=60) for t in bank if t["id"] not in paid}
            flagged = {i for i, s in statuses.items() if s == "missing_document"}
            expected = {t["txn_id"] for t in truth if t["doc_missing"]}
            with self.subTest(seed=seed):
                self.assertEqual(flagged, expected)
                noise = [t for t in bank if t["id"].startswith("txn_N")]
                self.assertTrue(all(statuses[t["id"]] == ("no_document_needed" if t["amount"]["amount"].startswith("-")
                                                         else None) for t in noise))


if __name__ == "__main__":
    unittest.main()
