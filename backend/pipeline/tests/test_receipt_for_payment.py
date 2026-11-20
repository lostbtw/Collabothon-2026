import copy
import unittest

from backend.pipeline.handlers import Context, linked_transaction
from backend.pipeline.match import THRESHOLD, run_matching, score_pair
from backend.pipeline.tests.schema_check import fixture
from backend.pipeline.tests.test_pipeline_handlers import MemoryStore

COMPANY = {"id": "co_borsuk", "tax_id": "9990000014"}
ACCOUNTS = [a for a in fixture("account") if a["company_id"] == "co_borsuk"]
RECEIPT = next(d for d in fixture("document") if d["id"] == "doc_rcpt412")
CARD_LINE = next(t for t in fixture("transaction") if t["id"] == "txn_731")


def receipt():
    doc = copy.deepcopy(RECEIPT)
    doc["payment"]["card_last4"] = "4417"
    return doc


def line(id, amount="-1299.00", booked="2026-11-20", name="ELEKTROMARKT POLSKA WARSZAWA", card="4417"):
    return {**copy.deepcopy(CARD_LINE), "id": id, "external_id": id, "match_status": "missing_document",
            "card_last4": card, "recurring_series_id": None, "fx": None, "original_amount": None, "booking_date": booked,
            "amount": {"amount": amount, "currency": "PLN"}, "amount_base": {"amount": amount, "currency": "PLN"},
            "counterparty_name_raw": name, "description": f"{name} KARTA *4417"}


def run(lines, linked=None):
    [result] = run_matching([receipt()], lines, company=COMPANY, people=[], accounts=ACCOUNTS,
                            now="2026-11-21T10:15:00Z", as_of="2026-11-21", linked=linked)
    return result["match"]


class OwnerAddsReceiptToPayment(unittest.TestCase):
    def test_the_chosen_line_wins_over_a_better_scoring_one(self):
        lines = [line("txn_a"), line("txn_b", booked="2026-11-22", name="SKLEP 0042")]
        self.assertEqual(run(lines)["transaction_id"], "txn_a")
        self.assertEqual(run(lines, {"doc_rcpt412": "txn_b"})["transaction_id"], "txn_b")

    def test_the_chosen_line_is_taken_below_the_threshold(self):
        weak = line("txn_weak", amount="-1299.80", booked="2026-11-24", name="ZZQ", card="0042")
        score, _ = score_pair(receipt(), weak, {a["id"]: a for a in ACCOUNTS})
        self.assertLess(score, THRESHOLD)
        self.assertIsNone(run([weak])["transaction_id"])
        self.assertEqual(run([weak], {"doc_rcpt412": "txn_weak"})["transaction_id"], "txn_weak")

    def test_a_line_with_another_amount_is_not_forced(self):
        other = line("txn_other", amount="-1349.00")
        match = run([other], {"doc_rcpt412": "txn_other"})
        self.assertIsNone(match["transaction_id"])
        self.assertEqual(match["match_type"], "document_no_transaction")

    def test_the_link_comes_from_the_uploaded_raw_item(self):
        store = MemoryStore()
        store.add("raw_item", {"id": "raw_up1", "kind": "upload", "metadata": {"for_transaction_id": "txn_b"}})
        ctx = Context(store=store, publish=lambda *a: None, company=lambda c: COMPANY, people=lambda c: [],
                      raw_bytes=lambda raw: None)
        self.assertEqual(linked_transaction(ctx, {"raw_item_ids": ["raw_up1"]}), "txn_b")
        self.assertIsNone(linked_transaction(ctx, {"raw_item_ids": ["raw_missing"]}))
