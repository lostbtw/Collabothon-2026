"""Ticket #25: who paid and its consequences. Run from the repo root:
    python -m unittest discover -s backend/pipeline/tests -t .
"""
import copy
import unittest

from backend.pipeline.tests.schema_check import fixture, schema_errors
from backend.pipeline.who_paid import (apply_who_paid, document_flags, has_tax_consequence,
                                       match_for_unmatched_document)

COMPANY = {"id": "co_borsuk", "tax_id": "PL9990000014"}
PEOPLE = [  # SAMPLE people, as role 5 seeds them from role 4's scenario
    {"person_id": "per_jan", "name": "Jan Kowalski (SAMPLE)", "email": "jan@borsuk-labs.sample", "role": "employee"},
    {"person_id": "per_owner", "name": "Ewa Borsuk (SAMPLE)", "email": "ewa@borsuk-labs.sample", "role": "owner"},
]
ACCOUNTS = [a for a in fixture("account") if a["company_id"] == "co_borsuk"]
DOCS = {d["id"]: d for d in fixture("document")}
MATCHES = {m["id"]: m for m in fixture("match")}
TXNS = {t["id"]: t for t in fixture("transaction")}
NOW, AS_OF = "2026-11-21T10:14:55Z", "2026-11-21"


def receipt(gross="1299.00", vat="242.90", buyer_nip=None, card="7730", sender="jan@borsuk-labs.sample",
            description="Monitor 27 cali QHD (SAMPLE)"):
    doc = copy.deepcopy(DOCS["doc_rcpt412"])
    doc["totals"]["gross"]["amount"] = doc["totals"]["gross_base"]["amount"] = gross
    doc["totals"]["vat"]["amount"] = vat
    doc["vat_lines"][0]["vat"] = vat
    doc["buyer"]["tax_id"] = buyer_nip
    doc["buyer"]["is_company"] = buyer_nip is not None
    doc["payment"]["card_last4"] = card
    doc["submitted_by"] = {"person_id": None, "name": None, "email": sender, "role": "unknown"}
    doc["lines"][0]["description"] = description
    doc["category_suggestion"] = None
    return doc


def unmatched(doc, transactions=(), sender=None):
    return match_for_unmatched_document(doc, company=COMPANY, people=PEOPLE, accounts=ACCOUNTS,
                                        transactions=list(transactions), now=NOW, as_of=AS_OF, sender_email=sender)


class HeroReceipt(unittest.TestCase):
    def setUp(self):
        self.match = unmatched(DOCS["doc_rcpt412"], sender="jan@borsuk-labs.sample")
        self.expected = MATCHES["mat_412"]

    def test_valid_against_the_contract(self):
        self.assertEqual(schema_errors(self.match, "match"), [])

    def test_shaped_like_fixture_mat_412(self):
        for field in ("match_type", "document_id", "transaction_id", "score", "reasons", "paid_by", "payer", "status"):
            self.assertEqual(self.match[field], self.expected[field], field)
        got, want = self.match["consequences"], self.expected["consequences"]
        for field in ("reimbursement_owed", "reimbursement_to", "vat_deductible", "vat_amount", "vat_lost", "rule_ids"):
            self.assertEqual(got[field], want[field], field)
        self.assertTrue(got["note"].startswith(want["note"]))

    def test_waits_for_the_owner(self):
        self.assertTrue(has_tax_consequence(self.match["consequences"]))
        self.assertEqual(self.match["status"], "suggested")

    def test_document_flags(self):
        flags = document_flags(DOCS["doc_rcpt412"], self.match["consequences"])
        self.assertEqual(flags, ["buyer_not_company", "vat_not_deductible"])


class DecisionTable(unittest.TestCase):
    def test_company_card_line_reverse_charge_matches_fixture(self):
        base = {k: v for k, v in MATCHES["mat_pixel11"].items() if k not in ("paid_by", "payer", "consequences")}
        match = apply_who_paid(base, DOCS["doc_pixel11"], TXNS["txn_731"], company=COMPANY, people=PEOPLE,
                               accounts=ACCOUNTS)
        self.assertEqual(match["paid_by"], "company_account")
        self.assertIsNone(match["payer"])
        self.assertEqual(match["consequences"], MATCHES["mat_pixel11"]["consequences"])
        self.assertFalse(has_tax_consequence(match["consequences"]))  # reverse charge alone may auto-confirm
        self.assertEqual(schema_errors(match, "match"), [])

    def test_employee_receipt_with_company_nip_keeps_vat(self):
        c = unmatched(receipt(buyer_nip="9990000014"))["consequences"]
        self.assertTrue(c["vat_deductible"])
        self.assertIsNone(c["vat_lost"])
        self.assertEqual(c["reimbursement_owed"], {"amount": "1299.00", "currency": "PLN"})
        self.assertEqual(c["rule_ids"], ["PL-REIMB-01"])

    def test_small_receipt_with_company_nip_is_a_simplified_invoice(self):
        c = unmatched(receipt(gross="450.00", vat="84.15", buyer_nip="PL9990000014"))["consequences"]
        self.assertTrue(c["vat_deductible"])
        self.assertIn("PL-VAT-02", c["rule_ids"])

    def test_receipt_over_450_is_not_a_simplified_invoice(self):
        c = unmatched(receipt(gross="450.01", vat="84.15", buyer_nip="9990000014"))["consequences"]
        self.assertNotIn("PL-VAT-02", c["rule_ids"])

    def test_unknown_sender(self):
        m = unmatched(receipt(sender="someone@else.sample"))
        self.assertEqual((m["paid_by"], m["payer"]), ("unknown", None))
        self.assertIsNone(m["consequences"]["reimbursement_owed"])
        self.assertLess(m["score"], 0.55)  # becomes a question, not a card to confirm

    def test_owner_private_card_is_owed_to_owner_and_loses_vat(self):
        m = unmatched(receipt(card="9021", sender="ewa@borsuk-labs.sample"))
        c = m["consequences"]
        self.assertEqual(m["paid_by"], "owner_private")
        self.assertEqual(c["reimbursement_to"]["person_id"], "per_owner")
        self.assertEqual(c["vat_lost"], {"amount": "242.90", "currency": "PLN"})
        self.assertEqual(c["rule_ids"], ["PL-VAT-01", "PL-REIMB-01"])
        self.assertEqual(schema_errors(m, "match"), [])

    def test_company_card_not_booked_yet(self):
        m = unmatched(receipt(card="4417"))
        self.assertEqual(m["paid_by"], "company_account")
        self.assertIsNone(m["consequences"]["reimbursement_owed"])
        self.assertIn("Ask for an invoice to the company next time.", m["consequences"]["note"])

    def test_private_looking_purchase_paid_by_company(self):
        txn = dict(TXNS["txn_731"], amount_base={"amount": "-180.00", "currency": "PLN"})
        doc = receipt(gross="180.00", vat="33.66", buyer_nip="9990000014", card="4417",
                      description="Perfumy 100 ml (SAMPLE)")
        base = {k: v for k, v in MATCHES["mat_pixel11"].items() if k not in ("paid_by", "payer", "consequences")}
        m = apply_who_paid(base, doc, txn, company=COMPANY, people=PEOPLE, accounts=ACCOUNTS)
        self.assertIn("PL-PRIV-01", m["consequences"]["rule_ids"])
        self.assertTrue(m["consequences"]["note"].endswith("Confirm with your accountant."))
        self.assertTrue(has_tax_consequence(m["consequences"]))
        self.assertIn("possible_private", document_flags(doc, m["consequences"]))

    def test_bank_line_in_window_removes_the_no_line_reason(self):
        line = dict(TXNS["txn_731"], booking_date="2026-11-20", amount_base={"amount": "-1299.00", "currency": "PLN"})
        rules = [r["rule"] for r in unmatched(DOCS["doc_rcpt412"], [line])["reasons"]]
        self.assertNotIn("no_bank_line_on_connected_accounts", rules)


if __name__ == "__main__":
    unittest.main()
