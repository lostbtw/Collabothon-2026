"""Counterparty resolution with alias learning, categories from the fixed list."""
import copy
import unittest

from backend.pipeline import counterparty as cpmod
from backend.pipeline.normalise import commerzbank_csv, normalise_bank_line
from backend.pipeline.tests.schema_check import fixture, schema_errors
from backend.pipeline.tests.test_pipeline_handlers import COMPANY, DOCS, RAW, Pipeline


def pixel_line(raw_id: str, ref: str, day: str) -> dict:
    raw = copy.deepcopy(RAW["raw_bank731"])
    raw.update(id=raw_id, external_id=ref, idempotency_key=(raw_id * 8)[:64].ljust(64, "0").replace("_", "0"))
    raw["payload"].update(entryReference=ref, bookingDate=day, valueDate=day, proprietaryBankTransactionCode="CARD_PAYMENT")
    return raw


def confirm(p: Pipeline, document_id: str) -> dict:
    [match] = p.store.list("match", document_id=document_id)
    p.store.put("match", {**match, "status": "confirmed", "decided_at": "2026-11-21T11:00:00Z",
                          "decided_by": {"role": "owner", "person_id": "per_tomek", "name": None, "email": None}})
    p.publish("match.decided", COMPANY, {"match_id": match["id"], "status": "confirmed", "approval_id": "apr_1"})
    p.run()
    return match


class PixelBoardLearns(unittest.TestCase):
    def check_second_line_resolves(self, p: Pipeline):
        cp_id = p.store.get("document", "doc_pixel11")["seller"]["counterparty_id"]
        first = p.store.get("transaction", "txn_pln_E000000731")
        self.assertEqual((first["counterparty_id"], first["data_quality"]), (cp_id, []))
        cp = p.store.get("counterparty", cp_id)
        self.assertIn("PIXELBOARD COM SAN FRANCISCO", cp["aliases"])
        self.assertEqual(cp["default_category"], "software_subscriptions")
        self.assertEqual(schema_errors(cp, "counterparty"), [])
        p.receive_raw(pixel_line("raw_bank990", "E000000990", "2026-12-20"))
        second = p.store.get("transaction", "txn_pln_E000000990")
        self.assertEqual((second["counterparty_id"], second["data_quality"], second["category"]),
                         (cp_id, [], "software_subscriptions"))
        self.assertEqual(schema_errors(second, "transaction"), [])

    def test_document_first_then_line_then_owner_confirms(self):
        p = Pipeline()
        p.extracted(copy.deepcopy(DOCS["doc_pixel11"]))
        p.receive_raw(pixel_line("raw_bank731", "E000000731", "2026-11-20"))
        line = p.store.get("transaction", "txn_pln_E000000731")
        self.assertIsNone(line["counterparty_id"])
        self.assertEqual(line["data_quality"], ["counterparty_unresolved"])
        confirm(p, "doc_pixel11")
        self.check_second_line_resolves(p)

    def test_line_first_then_document_then_owner_confirms(self):
        p = Pipeline()
        p.receive_raw(pixel_line("raw_bank731", "E000000731", "2026-11-20"))
        auto_created = p.store.get("transaction", "txn_pln_E000000731")["counterparty_id"]
        self.assertIsNotNone(auto_created)
        p.extracted(copy.deepcopy(DOCS["doc_pixel11"]))
        confirm(p, "doc_pixel11")
        self.check_second_line_resolves(p)
        self.assertNotIn("PIXELBOARD COM SAN FRANCISCO", p.store.get("counterparty", auto_created)["aliases"])

    def test_rejection_teaches_nothing(self):
        p = Pipeline()
        p.extracted(copy.deepcopy(DOCS["doc_pixel11"]))
        p.receive_raw(pixel_line("raw_bank731", "E000000731", "2026-11-20"))
        [match] = p.store.list("match", document_id="doc_pixel11")
        p.store.put("match", {**match, "status": "rejected"})
        p.publish("match.decided", COMPANY, {"match_id": match["id"], "status": "rejected", "approval_id": "apr_2"})
        p.run()
        cp_id = p.store.get("document", "doc_pixel11")["seller"]["counterparty_id"]
        self.assertEqual(p.store.get("counterparty", cp_id)["aliases"], ["PIXELBOARD INC SAMPLE"])


class Resolution(unittest.TestCase):
    def test_same_tax_id_different_spelling_is_one_counterparty(self):
        known = [fixture("counterparty")[0]]
        doc = copy.deepcopy(DOCS["doc_rcpt412"])
        doc["seller"] = {**doc["seller"], "name": "ELEKTRO MARKT POLSKA SA", "counterparty_id": None}
        updated, store = cpmod.apply_to_document(doc, known, COMPANY)
        self.assertEqual(updated["seller"]["counterparty_id"], "cp_elektromarkt")
        self.assertIn("ELEKTRO MARKT POLSKA SA", store["aliases"])

    def test_iban_wins_over_name(self):
        known = [fixture("counterparty")[1]]
        txn = copy.deepcopy(fixture("transaction")[0])
        txn.update(counterparty_name_raw="SOMETHING ELSE", counterparty_account="DE00 SAMPLE 0000 0000 00",
                   amount_base={"amount": "18400.00", "currency": "PLN"})
        updated, new_cp = cpmod.apply_to_transaction(txn, known, COMPANY)
        self.assertEqual((updated["counterparty_id"], new_cp), ("cp_nordwind", None))
        self.assertEqual(updated["category"], "revenue_services")

    def test_reference_numbers_do_not_split_aliases(self):
        self.assertEqual(cpmod.normalise_alias("PIXELBOARD.COM* SAN FRANCISCO 1452"),
                         cpmod.normalise_alias("PIXELBOARD.COM* SAN FRANCISCO 9638"))


class Categories(unittest.TestCase):
    def test_model_is_asked_only_when_rules_do_not_decide_and_must_answer_from_the_list(self):
        asked = []

        def choose(question, choices):
            asked.append(question)
            return "marketing_ads" if "Kampania" in question else "not a category"

        self.assertEqual(cpmod.categorise("Kampania jesienna SAMPLE", counterparty=None, incoming=False,
                                          choose=choose), ("marketing_ads", "llm", 0.7))
        self.assertEqual(cpmod.categorise("Zzz SAMPLE", counterparty=None, incoming=False, choose=choose)[0], "other")
        self.assertEqual(cpmod.categorise("WYNAGRODZENIE 10/2026", counterparty=None, incoming=False,
                                          choose=choose)[0], "salaries")
        self.assertEqual(len(asked), 2)

    @unittest.skipUnless(commerzbank_csv.DEFAULT_CSV.exists(), "pizzeria CSV not present")
    def test_pizzeria_year(self):
        account = next(a for a in fixture("account") if a["id"] == "acc_pizzeria")
        cps, txns = [], []
        for raw in commerzbank_csv.raw_items(commerzbank_csv.read_booked_lines()):
            txn, new_cp = cpmod.apply_to_transaction(normalise_bank_line(raw, account), cps, "co_amalfi")
            if new_cp:
                cps.append(new_cp)
            txns.append(txn)
        self.assertTrue(all(t["category"] in cpmod.CATEGORIES for t in txns))
        self.assertLessEqual(len(cps), 20)
        self.assertEqual([e for c in cps for e in schema_errors(c, "counterparty")], [])
        by_payee = {}
        for t in txns:
            by_payee.setdefault(t["counterparty_name_raw"], set()).add(t["category"])
        expected = {"Techniker Krankenkasse Social Health Fund": {"social_security"},
                    "Tax Office Frankfurt am Main": {"taxes"},
                    "Main Street Real Estate GmbH": {"rent_office"},
                    "Luigi Amalfi (Luigi's Ristorante Zurich)": {"investment_outflow"},
                    "Commerzbank Global Pay": {"revenue_services"},
                    "Yusuf Akcit": {"salaries"}}
        for payee, categories in expected.items():
            self.assertEqual(by_payee[payee], categories, payee)


if __name__ == "__main__":
    unittest.main()
