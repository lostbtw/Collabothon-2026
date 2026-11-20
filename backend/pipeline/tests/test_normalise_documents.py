"""Ticket #23: FA(3) XML and inFakt JSON -> Documents, PL-FX-01 conversion."""
import unittest
from pathlib import Path

from backend.pipeline.normalise.fa3 import Fa3Error, parse_fa3
from backend.pipeline.normalise.fx import StandInRates
from backend.pipeline.normalise.infakt import parse_infakt
from backend.pipeline.tests.schema_check import fixture, schema_errors

SAMPLE_XML = (Path(__file__).parent / "data" / "fa3_hosting_sample.xml").read_text(encoding="utf-8")
BORSUK = {"id": "co_borsuk", "name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "9990000014"}
RAW = {"id": "raw_ksef0417", "fetched_at": "2026-11-05T08:01:00Z"}


def usd_invoice(issue_date: str) -> str:
    xml = SAMPLE_XML.replace("<KodWaluty>PLN</KodWaluty>", "<KodWaluty>USD</KodWaluty>")
    xml = xml.replace("<P_1>2026-11-05</P_1>", f"<P_1>{issue_date}</P_1>")
    xml = xml.replace("<P_13_1>390.00</P_13_1>", "<P_13_10>45.00</P_13_10>").replace("<P_14_1>89.70</P_14_1>", "")
    return xml.replace("<P_15>479.70</P_15>", "<P_15>45.00</P_15>")


class Fa3Invoice(unittest.TestCase):
    def test_pln_purchase_invoice(self):
        doc = parse_fa3(SAMPLE_XML, RAW, BORSUK)
        self.assertEqual(schema_errors(doc, "document"), [])
        self.assertEqual((doc["id"], doc["channel"], doc["doc_type"], doc["direction"]),
                         ("doc_ksef0417", "ksef", "invoice", "purchase"))
        self.assertEqual(doc["number"], "FV/11/2026/0417")
        self.assertEqual((doc["issue_date"], doc["sale_date"], doc["due_date"]),
                         ("2026-11-05", "2026-10-31", "2026-11-19"))
        self.assertEqual(doc["seller"]["tax_id"], "9990000103")
        self.assertTrue(doc["buyer"]["is_company"])
        self.assertEqual(doc["totals"]["net"], {"amount": "390.00", "currency": "PLN"})
        self.assertEqual(doc["totals"]["vat"], {"amount": "89.70", "currency": "PLN"})
        self.assertEqual(doc["totals"]["gross"], {"amount": "479.70", "currency": "PLN"})
        self.assertEqual(doc["totals"]["gross_base"], doc["totals"]["gross"])
        self.assertIsNone(doc["totals"]["fx"])
        self.assertEqual(doc["vat_lines"], [{"rate": "23", "net": "390.00", "vat": "89.70"}])
        self.assertEqual(doc["payment"]["method"], "transfer")
        self.assertEqual(doc["payment"]["bank_account"], "99999900000000000000000103")
        self.assertEqual(doc["extraction"]["confidence"], 1.0)
        self.assertEqual(doc["flags"], [])

    def test_sale_when_company_is_the_seller(self):
        doc = parse_fa3(SAMPLE_XML, RAW, {"id": "co_chmura", "tax_id": "PL9990000103"})
        self.assertEqual(doc["direction"], "sale")

    def test_foreign_currency_uses_previous_business_day_nbp_rate(self):
        doc = parse_fa3(usd_invoice("2026-11-19"), RAW, BORSUK, rates=StandInRates())
        self.assertEqual(schema_errors(doc, "document"), [])
        expected = next(d for d in fixture("document") if d["id"] == "doc_pixel11")["totals"]
        self.assertEqual(doc["totals"]["gross_base"], expected["gross_base"])  # 45.00 x 3.9099 = 175.95 PLN
        self.assertEqual(doc["totals"]["fx"], expected["fx"])
        self.assertEqual(doc["flags"], ["foreign_currency", "reverse_charge"])

    def test_rate_lookup_skips_the_weekend(self):
        rates = StandInRates({("USD", "2026-11-20"): ("3.9500", "226/A/NBP/2026")})  # Friday
        doc = parse_fa3(usd_invoice("2026-11-23"), RAW, BORSUK, rates=rates)  # Monday
        self.assertEqual(doc["totals"]["fx"]["rate_date"], "2026-11-20")
        self.assertEqual(doc["totals"]["fx"]["source"], "NBP table A 226/A/NBP/2026")
        self.assertEqual(doc["totals"]["gross_base"], {"amount": "177.75", "currency": "PLN"})

    def test_missing_rate_leaves_gross_base_empty_with_warning(self):
        doc = parse_fa3(usd_invoice("2024-06-03"), RAW, BORSUK, rates=StandInRates())  # before the table
        self.assertIsNone(doc["totals"]["gross_base"])
        self.assertEqual(len(doc["extraction"]["warnings"]), 1)
        self.assertEqual(schema_errors(doc, "document"), [])

    def test_rejects_other_xml(self):
        with self.assertRaises(Fa3Error):
            parse_fa3("<Invoice/>", RAW, BORSUK)


class InfaktInvoice(unittest.TestCase):
    INVOICE = {
        "number": "FV 12/11/2026", "kind": "vat", "currency": "PLN",
        "invoice_date": "2026-11-10", "sale_date": "2026-11-10", "payment_date": "2026-11-24",
        "payment_method": "transfer", "status": "sent",
        "net_price": 3000000, "tax_price": 690000, "gross_price": 3690000,  # grosze
        "client_company_name": "Meblostyl sp. z o.o. (SAMPLE)", "client_tax_code": "9990000043",
        "client_street": "ul. Fikcyjna", "client_street_number": "3", "client_post_code": "00-002",
        "client_city": "Kraków", "client_country": "PL",
        "services": [{"name": "Shop integration, November (SAMPLE)", "quantity": 1, "unit_net_price": 3000000,
                      "net_price": 3000000, "tax_price": 690000, "tax_symbol": "23"}],
    }

    def test_sales_invoice(self):
        doc = parse_infakt(self.INVOICE, {"id": "raw_infakt12", "fetched_at": "2026-11-10T09:00:00Z"}, BORSUK)
        self.assertEqual(schema_errors(doc, "document"), [])
        self.assertEqual((doc["direction"], doc["channel"], doc["doc_type"]), ("sale", "accounting_api", "invoice"))
        self.assertEqual(doc["totals"]["gross"], {"amount": "36900.00", "currency": "PLN"})
        self.assertEqual(doc["vat_lines"], [{"rate": "23", "net": "30000.00", "vat": "6900.00"}])
        self.assertEqual(doc["seller"]["tax_id"], "9990000014")
        self.assertEqual(doc["buyer"]["address"], "ul. Fikcyjna 3, 00-002 Kraków")
        self.assertIs(doc["payment"]["paid"], False)
        self.assertEqual(doc["due_date"], "2026-11-24")


if __name__ == "__main__":
    unittest.main()
