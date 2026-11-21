"""Bank lines -> Transactions."""
import unittest
from decimal import Decimal

from backend.pipeline.normalise import NormaliseError, normalise_bank_line, transaction_ingested_payload
from backend.pipeline.normalise import commerzbank_csv
from backend.pipeline.tests.schema_check import fixture, schema_errors

ACCOUNTS = {a["id"]: a for a in fixture("account")}
OWN_FIELDS = ("account_id", "source_id", "raw_item_id", "external_id", "booking_date", "amount", "amount_base",
              "fx", "original_amount", "counterparty_name_raw", "description", "transaction_type", "card_last4",
              "status", "data_quality")


class FixtureBankLine(unittest.TestCase):
    def test_pixelboard_card_line_matches_fixture(self):
        raw = next(r for r in fixture("raw_item") if r["id"] == "raw_bank731")
        raw = {**raw, "payload": {**raw["payload"], "valueDate": "2026-11-19",
                                  "proprietaryBankTransactionCode": "CARD_PAYMENT"}}
        txn = normalise_bank_line(raw, ACCOUNTS["acc_pln"])
        expected = next(t for t in fixture("transaction") if t["id"] == "txn_731")
        for field in OWN_FIELDS:
            self.assertEqual(txn[field], expected[field], field)
        self.assertEqual(schema_errors(txn, "transaction"), [])

    def test_same_line_twice_gives_same_id(self):
        raw = next(r for r in fixture("raw_item") if r["id"] == "raw_bank731")
        a = normalise_bank_line(raw, ACCOUNTS["acc_pln"])
        b = normalise_bank_line(raw, ACCOUNTS["acc_pln"])
        self.assertEqual(a["id"], b["id"])

    def test_foreign_currency_without_rate_fails(self):
        raw = {"id": "raw_x", "source_id": "src_bank_pizzeria", "payload": {
            "entryReference": "E1", "bookingDate": "2025-06-15",
            "transactionAmount": {"amount": "-10.00", "currency": "CHF"},
            "remittanceInformationUnstructured": "no rate here"}}
        with self.assertRaises(NormaliseError):
            normalise_bank_line(raw, ACCOUNTS["acc_pizzeria"])

    def test_event_payload(self):
        raw = next(r for r in fixture("raw_item") if r["id"] == "raw_bank731")
        txn = normalise_bank_line(raw, ACCOUNTS["acc_pln"])
        self.assertEqual(transaction_ingested_payload(txn), {
            "transaction_id": txn["id"], "account_id": "acc_pln",
            "amount": {"amount": "-185.57", "currency": "PLN"}, "booking_date": "2026-11-20"})


@unittest.skipUnless(commerzbank_csv.DEFAULT_CSV.exists(), f"put the CSV at {commerzbank_csv.DEFAULT_CSV}")
class PizzeriaStatement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = commerzbank_csv.raw_items(commerzbank_csv.read_booked_lines())
        cls.txns = [normalise_bank_line(r, ACCOUNTS["acc_pizzeria"]) for r in cls.items]

    def test_raw_items_follow_the_contract(self):
        self.assertEqual([e for r in self.items[:50] for e in schema_errors(r, "raw_item")], [])

    def test_all_lines_become_valid_transactions(self):
        self.assertEqual(len(self.txns), 1125)
        errors = [e for t in self.txns for e in schema_errors(t, "transaction")]
        self.assertEqual(errors[:5], [])
        self.assertEqual(len({t["id"] for t in self.txns}), 1125)

    def test_year_end_balance(self):
        opening = Decimal(ACCOUNTS["acc_pizzeria"]["opening_balance"]["amount"])
        total = sum(Decimal(t["amount_base"]["amount"]) for t in self.txns)
        self.assertTrue(all(t["amount_base"]["currency"] == "EUR" for t in self.txns))
        self.assertEqual(opening + total, Decimal("33266.35"))

    def test_twelve_chf_lines_converted_and_flagged(self):
        chf = [t for t in self.txns if t["amount"]["currency"] == "CHF"]
        self.assertEqual(len(chf), 12)
        for t in chf:
            self.assertEqual(t["data_quality"], ["currency_mismatch_fixed", "rate_from_reference_text"])
            self.assertEqual(t["fx"]["rule"], "statement_reference")
        others = [t for t in self.txns if t["amount"]["currency"] == "EUR"]
        self.assertTrue(all(t["data_quality"] == [] and t["fx"] is None for t in others))

    def test_june_chf_line_matches_fixture(self):
        txn = next(t for t in self.txns if t["booking_date"] == "2025-06-15" and t["amount"]["currency"] == "CHF")
        expected = next(t for t in fixture("transaction") if t["id"] == "txn_pz0615")
        for field in ("amount", "amount_base", "fx", "original_amount", "counterparty_name_raw",
                      "counterparty_account", "description", "transaction_type", "data_quality"):
            self.assertEqual(txn[field], expected[field], field)

    def test_transaction_types(self):
        by_type = {}
        for t in self.txns:
            by_type[t["transaction_type"]] = by_type.get(t["transaction_type"], 0) + 1
        self.assertEqual(by_type, {"card_settlement": 478, "card_payment": 292, "transfer_out": 263, "salary": 48,
                                   "tax": 20, "social_security": 12, "direct_debit": 12})

    def test_entry_reference_strictly_increasing_and_chronological(self):
        refs = [t["external_id"] for t in self.txns]
        self.assertEqual(refs, sorted(refs))
        dates = [t["booking_date"] for t in self.txns]
        self.assertEqual(dates, sorted(dates))


if __name__ == "__main__":
    unittest.main()
