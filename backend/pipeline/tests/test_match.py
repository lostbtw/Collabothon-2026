"""Ticket #24: match scoring, assignment and routing. Run from the repo root:
    python -m unittest discover -s backend/pipeline/tests -t .
"""
import copy
import unittest
from decimal import Decimal

from backend.pipeline.match import match_suggested_payload, run_matching, score_pair
from backend.pipeline.tests import generated_world as world
from backend.pipeline.tests.schema_check import fixture, schema_errors

COMPANY = {"id": "co_borsuk", "tax_id": "PL9990000014"}
PEOPLE = [{"person_id": "per_jan", "name": "Jan Kowalski (SAMPLE)", "email": "jan@borsuk-labs.sample", "role": "employee"},
          {"person_id": "per_owner", "name": "Ewa Borsuk (SAMPLE)", "email": "ewa@borsuk-labs.sample", "role": "owner"}]
ACCOUNTS = [a for a in fixture("account") if a["company_id"] == "co_borsuk"]
BY_ACCOUNT = {a["id"]: a for a in ACCOUNTS}
DOCS = {d["id"]: d for d in fixture("document")}
TXNS = {t["id"]: t for t in fixture("transaction")}
NOW = "2026-11-21T10:15:00Z"


def run(docs, txns, **kw):
    return run_matching(docs, txns, company=COMPANY, people=PEOPLE, accounts=ACCOUNTS, now=NOW, as_of="2026-11-21", **kw)


def line(**changes):
    txn = copy.deepcopy(TXNS["txn_731"])
    txn.update(match_status="unmatched", recurring_series_id=None)
    txn.update(changes)
    return txn


class PixelBoard(unittest.TestCase):
    def test_auto_confirms_known_recurring_series(self):
        [result] = run([DOCS["doc_pixel11"]], [line(recurring_series_id="ser_pixelboard")])
        match, expected = result["match"], fixture("match")[1]
        self.assertEqual(schema_errors(match, "match"), [])
        self.assertEqual(match["transaction_id"], "txn_731")
        self.assertEqual([r["rule"] for r in match["reasons"]], [r["rule"] for r in expected["reasons"]])
        weights = {r["rule"]: r["weight"] for r in match["reasons"]}
        self.assertEqual((weights["amount_fx_within_spread"], weights["date_lag"], weights["card_last4"]),
                         (0.35, 0.18, 0.12))
        self.assertGreaterEqual(match["score"], 0.90)
        self.assertIn("+2.7%", match["reasons"][0]["detail"])
        self.assertEqual((match["status"], match["decided_by"], result["control_level"]),
                         ("auto_confirmed", expected["decided_by"], "analysed_autonomously"))
        self.assertEqual(match["consequences"], expected["consequences"])

    def test_without_recurring_series_waits_for_one_click(self):
        [result] = run([DOCS["doc_pixel11"]], [line()])
        self.assertEqual((result["match"]["status"], result["control_level"]), ("suggested", "approval_required"))

    def test_event_payload(self):
        [result] = run([DOCS["doc_pixel11"]], [line()])
        self.assertEqual(match_suggested_payload(result["match"]),
                         {"match_id": "mat_pixel11", "document_id": "doc_pixel11", "transaction_id": "txn_731",
                          "paid_by": "company_account", "score": result["match"]["score"]})


class Rules(unittest.TestCase):
    def receipt_on_company_card(self):
        doc = copy.deepcopy(DOCS["doc_rcpt412"])
        doc["payment"]["card_last4"] = "4417"
        txn = line(id="txn_em", amount={"amount": "-1299.00", "currency": "PLN"},
                   amount_base={"amount": "-1299.00", "currency": "PLN"}, fx=None, original_amount=None,
                   counterparty_name_raw="ELEKTROMARKT POLSKA WARSZAWA", description="ELEKTROMARKT POLSKA KARTA *4417",
                   booking_date="2026-11-20", recurring_series_id="ser_em")
        return doc, txn

    def test_tax_consequence_is_never_auto_confirmed(self):
        doc, txn = self.receipt_on_company_card()
        [result] = run([doc], [txn])
        match = result["match"]
        self.assertGreaterEqual(match["score"], 0.90)
        self.assertEqual(match["consequences"]["vat_lost"], {"amount": "242.90", "currency": "PLN"})
        self.assertEqual((match["status"], result["control_level"]), ("suggested", "approval_required"))

    def test_amount_more_than_one_off_is_no_match(self):
        doc, txn = self.receipt_on_company_card()
        txn["amount_base"] = {"amount": "-1300.01", "currency": "PLN"}
        self.assertEqual(score_pair(doc, txn, BY_ACCOUNT), (0.0, []))

    def test_amount_within_one(self):
        doc, txn = self.receipt_on_company_card()
        txn["amount_base"] = {"amount": "-1299.90", "currency": "PLN"}
        _, reasons = score_pair(doc, txn, BY_ACCOUNT)
        self.assertEqual(reasons[0]["rule"], "amount_near")

    def test_card_line_outside_date_window_is_no_match(self):
        doc, txn = self.receipt_on_company_card()
        txn["booking_date"] = "2026-11-26"  # 6 days after
        self.assertEqual(score_pair(doc, txn, BY_ACCOUNT), (0.0, []))

    def test_incoming_money_never_pays_a_purchase(self):
        doc, txn = self.receipt_on_company_card()
        txn["amount_base"] = {"amount": "1299.00", "currency": "PLN"}
        self.assertEqual(score_pair(doc, txn, BY_ACCOUNT), (0.0, []))

    def test_fx_outside_spread_band_is_no_match(self):
        txn = line(amount_base={"amount": "-190.00", "currency": "PLN"})  # +5.1% over 180.77
        self.assertEqual(score_pair(DOCS["doc_pixel11"], txn, BY_ACCOUNT), (0.0, []))

    def test_transfer_with_invoice_number_and_iban(self):
        doc = copy.deepcopy(DOCS["doc_rcpt412"])
        doc.update(doc_type="invoice", number="FV/11/2026/0417", due_date="2026-12-04")
        doc["payment"].update(method="transfer", card_last4=None, bank_account="PL 99 9999 0000 0000 0000 0000 0103")
        txn = line(id="txn_tr", amount_base={"amount": "-1299.00", "currency": "PLN"}, card_last4=None, fx=None,
                   transaction_type="transfer_out", booking_date="2026-12-03",
                   counterparty_account="PL99999900000000000000000103", counterparty_name_raw="ElektroMarkt Polska",
                   description="Zaplata FV/11/2026/0417")
        score, reasons = score_pair(doc, txn, BY_ACCOUNT)
        rules = {r["rule"] for r in reasons}
        self.assertTrue({"amount_exact", "date_lag", "invoice_number_in_title", "iban_equal"} <= rules)
        self.assertEqual(score, 1.0)

    def test_one_bank_line_pays_one_document(self):
        doc, txn = self.receipt_on_company_card()
        twin = copy.deepcopy(doc)
        twin.update(id="doc_twin", number="PARAGON 009999/11/2026", issue_date="2026-11-17")
        results = run([doc, twin], [txn])
        matched = [r for r in results if r["match"]["transaction_id"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["match"]["document_id"], doc["id"])  # closer date wins
        other = next(r for r in results if not r["match"]["transaction_id"])
        self.assertEqual(other["match"]["match_type"], "document_no_transaction")

    def test_duplicates_are_skipped(self):
        doc, txn = self.receipt_on_company_card()
        self.assertEqual(run([dict(doc, status="duplicate")], [txn]), [])


class GeneratedWorld(unittest.TestCase):
    """Spike 04's 5 seeds, golden documents only (dedup is #40)."""

    def test_precision_who_paid_and_vat_lost(self):
        who_total = who_ok_total = 0
        for seed in range(1, 6):
            docs, bank, senders, truth = world.build(seed)
            results = run_matching(docs, bank, company=world.COMPANY, people=world.PEOPLE, accounts=world.ACCOUNTS,
                                   now=NOW, senders=senders)
            by_doc = {r["match"]["document_id"]: r["match"] for r in results}
            events = [t for t in truth if t["doc_id"]]
            matched = [t for t in events if by_doc[t["doc_id"]]["transaction_id"]]
            wrong = [t for t in matched if by_doc[t["doc_id"]]["transaction_id"] != t["txn_id"]]
            possible = [t for t in events if t["txn_id"]]
            who_ok = sum(by_doc[t["doc_id"]]["paid_by"] == t["paid_by"] for t in events)
            # "unknown" is allowed (it becomes a question to the owner); a wrong definite answer is not.
            who_wrong = [t for t in events if by_doc[t["doc_id"]]["paid_by"] not in (t["paid_by"], "unknown")]
            who_total, who_ok_total = who_total + len(events), who_ok_total + who_ok
            lost = sum(Decimal(by_doc[t["doc_id"]]["consequences"]["vat_lost"]["amount"])
                       for t in events if by_doc[t["doc_id"]]["consequences"]["vat_lost"])
            true_lost = sum(Decimal(f"{t['vat_lost']:.2f}") for t in events)
            with self.subTest(seed=seed):
                self.assertEqual(wrong, [], "precision must be 100%")
                self.assertGreaterEqual(len(matched) / max(1, len(possible)), 0.9, "recall")
                self.assertEqual(who_wrong, [], "who paid: no wrong definite answer")
                self.assertEqual(lost, true_lost, "VAT lost total")
        # Misses left are KSeF invoices an employee bought on the company NIP, never forwarded, no bank line:
        # nothing says who paid, so the owner is asked (paid_by = unknown), as the spec's table requires.
        self.assertGreaterEqual(who_ok_total / who_total, 0.97, f"who paid {who_ok_total}/{who_total}")


if __name__ == "__main__":
    unittest.main()
