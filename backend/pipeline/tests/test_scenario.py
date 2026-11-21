"""The whole pipeline on the demo scenario, checked against sim/scenario/out/ground_truth.json (~10 s)."""
import unittest

from backend.pipeline.tests import scenario as sc
from backend.pipeline.tests.schema_check import schema_errors

KNOWN_SCENARIO_ISSUES: dict[str, str] = {}
NEVER_MISSING = {"bank_fee", "tax_or_social_security", "salary", "reimbursement_payout", "internal_transfer"}


@unittest.skipUnless(sc.available(), "sim/scenario/out not present")
class Scenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r, cls.truth = sc.run(), sc.truth()
        cls.docs = {d["id"]: d for d in cls.r["documents"]}
        cls.match = {x["match"]["document_id"]: x["match"] for x in cls.r["results"]}

    def golden_match(self, truth_doc):
        doc = self.docs[sc.doc_id(truth_doc["document_id"])]
        return self.match[doc["duplicate_of"] or doc["id"]]

    def test_every_bank_line_and_document_follows_the_contract(self):
        self.assertEqual(len(self.r["transactions"]), self.truth["summary"]["bank_lines"])
        self.assertEqual(len(self.r["documents"]), self.truth["summary"]["documents"])
        errors = [e for t in self.r["transactions"] for e in schema_errors(t, "transaction")]
        errors += [e for d in self.r["documents"] for e in schema_errors(d, "document")]
        errors += [e for x in self.r["results"] for e in schema_errors(x["match"], "match")]
        self.assertEqual(errors[:5], [])

    def test_matching_is_never_wrong(self):
        wrong, missed, right = [], [], 0
        for t in self.truth["documents"]:
            if t["match_type"] == "duplicate_document":
                continue
            got, want = self.golden_match(t)["transaction_id"], sc.txn_id(t["bank_line"])
            if got == want:
                right += 1
            elif got is None:
                missed.append(t["document_id"])
            else:
                wrong.append((t["document_id"], want, got))
        self.assertEqual(wrong, [])
        self.assertEqual(set(missed) - set(KNOWN_SCENARIO_ISSUES), set())
        self.assertGreaterEqual(right, 540)

    def test_who_paid_and_vat_lost(self):
        who = [t["document_id"] for t in self.truth["documents"] if t["match_type"] != "duplicate_document"
               and t["paid_by"] and self.golden_match(t)["paid_by"] != t["paid_by"]]
        self.assertEqual(set(who) - set(KNOWN_SCENARIO_ISSUES), set())
        vat = [(t["document_id"], (t.get("vat_lost") or {}).get("amount"),
                (self.golden_match(t)["consequences"].get("vat_lost") or {}).get("amount"))
               for t in self.truth["documents"] if t["match_type"] != "duplicate_document"]
        self.assertEqual([v for v in vat if v[1] != v[2]], [])

    def test_hero_receipt(self):
        m = self.match["doc_rcpt412"]
        self.assertEqual((m["paid_by"], m["payer"]["person_id"], m["score"]), ("employee_private", "per_jan", 0.86))
        self.assertEqual(m["consequences"]["vat_lost"], {"amount": "242.90", "currency": "PLN"})

    def test_auto_confirmed_matches_are_all_right(self):
        want = {sc.doc_id(t["document_id"]): sc.txn_id(t["bank_line"]) for t in self.truth["documents"]
                if t["match_type"] != "duplicate_document"}
        auto = [m for m in self.match.values() if m["status"] == "auto_confirmed"]
        self.assertEqual([m["document_id"] for m in auto if want.get(m["document_id"]) != m["transaction_id"]], [])
        self.assertGreaterEqual(len(auto), 350)

    def test_duplicates(self):
        clusters = [set(c) for c in self.r["clusters"] if len(c) > 1]
        expected = [{sc.doc_id(c["original"])} | {sc.doc_id(x) for x in c["copies"]} for c in self.truth["duplicates"]]
        found = [c for c in expected if c in clusters]
        unexplained = [c for c in expected if c not in clusters and not c & {sc.doc_id(k) for k in KNOWN_SCENARIO_ISSUES}]
        self.assertEqual(unexplained, [])
        self.assertEqual([c for c in clusters if c not in expected], [], "no false duplicates")
        self.assertGreaterEqual(len(found), 4)

    def test_missing_documents(self):
        status = self.r["line_status"]
        for b in self.truth["bank_lines_without_document"]:
            got = status.get(sc.txn_id(b))
            if b["reason"] in NEVER_MISSING:
                self.assertNotEqual(got, "missing_document", b)
            if b["reason"] == "document_missing" and b["booking_date"] <= "2026-11-16":
                self.assertEqual(got, "missing_document", b)


if __name__ == "__main__":
    unittest.main()
