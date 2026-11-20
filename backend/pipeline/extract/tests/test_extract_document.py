import copy
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from backend.pipeline.extract.document import build_document

SCHEMAS = Path(__file__).resolve().parents[4] / "contracts" / "schemas"
TODAY = date(2026, 11, 21)
MODEL = "gpt-oss-20b"

HERO = {
    "doc_type": "receipt",
    "number": "PARAGON 004512/11/2026",
    "issue_date": "2026-11-20",
    "sale_date": None,
    "due_date": None,
    "seller": {"name": "ElektroMarkt Polska S.A. (SAMPLE)", "tax_id": "9990000043", "country": "PL", "address": None},
    "buyer": {"name": None, "tax_id": None, "country": None, "address": None},
    "currency": "PLN",
    "gross": "1299.00",
    "net": None,
    "vat": "242.90",
    "vat_lines": [{"rate": "23", "vat": "242.90", "gross": "1299.00"}],
    "lines": [{"description": "Monitor 27 cali QHD (SAMPLE)", "quantity": 1, "unit_price": "1299.00",
               "net": None, "vat_rate": "23"}],
    "payment_method": "card",
    "card_last4": "7730",
    "bank_account": None,
    "confidence": 0.93,
    "field_confidence": {"gross": 0.99, "net": 0.5, "vat": 0.96, "issue_date": 0.95, "number": 0.9,
                         "seller_tax_id": 0.97, "buyer_tax_id": 0.9},
}

USD_INVOICE = {
    "doc_type": "invoice",
    "number": "INV-2026-1107",
    "issue_date": "2026-11-07",
    "sale_date": "2026-11-07",
    "due_date": "2026-11-21",
    "seller": {"name": "Cloudscale Inc. (SAMPLE)", "tax_id": "US-99-0000007", "country": "US",
               "address": "1 Sample Way, Springfield"},
    "buyer": {"name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "PL9990000014", "country": "PL", "address": None},
    "currency": "USD",
    "gross": "480.00",
    "net": "480.00",
    "vat": "0.00",
    "vat_lines": [{"rate": "np I", "vat": "0.00", "gross": "480.00"}],
    "lines": [{"description": "Cloud hosting 11/2026", "quantity": "1", "unit_price": "480.00", "net": "480.00",
               "vat_rate": "np"}],
    "payment_method": "transfer",
    "card_last4": None,
    "bank_account": "US00999900000000000000070001",
    "confidence": 0.95,
    "field_confidence": {"gross": 0.98, "net": 0.98, "vat": 0.95, "issue_date": 0.97, "number": 0.95,
                         "seller_tax_id": 0.9, "buyer_tax_id": 0.97},
}

UNREADABLE = {
    "doc_type": "receipt",
    "seller": {"name": None, "tax_id": None},
    "buyer": {},
    "currency": None,
    "gross": None,
    "confidence": 0.2,
    "field_confidence": {"gross": 0.1},
}


def schema_errors(document):
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in (json.loads(path.read_text(encoding="utf-8")) for path in SCHEMAS.glob("*.schema.json")))
    schema = json.loads((SCHEMAS / "document.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    full = {"id": "doc_test", "company_id": "co_test", "raw_item_ids": ["raw_test"], "duplicate_of": None,
            "direction": "purchase", "channel": "photo", "submitted_by": None, **document}
    return sorted(f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(full))


def build(answer, **kwargs):
    return build_document(copy.deepcopy(answer), model=MODEL, today=TODAY, **kwargs)


@pytest.mark.parametrize("answer", [HERO, USD_INVOICE, UNREADABLE, {}], ids=["hero", "usd", "unreadable", "empty"])
def test_output_validates_against_the_document_schema(answer):
    assert schema_errors(build(answer)) == []


def test_hero_receipt_derives_net_and_is_extracted():
    doc = build(HERO)
    assert doc["totals"]["gross"] == {"amount": "1299.00", "currency": "PLN"}
    assert doc["totals"]["net"] == {"amount": "1056.10", "currency": "PLN"}
    assert doc["totals"]["vat"] == {"amount": "242.90", "currency": "PLN"}
    assert doc["totals"]["gross_base"] == {"amount": "1299.00", "currency": "PLN"}
    assert doc["vat_lines"] == [{"rate": "23", "net": "1056.10", "vat": "242.90"}]
    assert doc["extraction"]["field_confidence"]["net"] == 0.96
    assert doc["extraction"]["confidence"] == 0.93
    assert doc["status"] == "extracted"
    assert doc["flags"] == []


def test_extraction_block_names_the_method_and_model():
    extraction = build(HERO)["extraction"]
    assert extraction["method"] == "docling_llm"
    assert extraction["model"] == "gpt-oss-20b"
    assert extraction["trace_id"] is None


def test_no_buyer_printed_is_not_a_company():
    buyer = build(HERO)["buyer"]
    assert buyer["name"] == "(none printed)"
    assert buyer["is_company"] is False


def test_printed_buyer_tax_id_makes_the_buyer_a_company():
    answer = copy.deepcopy(HERO)
    answer["buyer"] = {"name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "9990000014"}
    assert build(answer)["buyer"]["is_company"] is True


def test_card_receipt_is_paid_on_its_issue_date():
    payment = build(HERO)["payment"]
    assert payment == {"method": "card", "card_last4": "7730", "paid": True, "paid_date": "2026-11-20",
                       "bank_account": None}


def test_invoice_by_transfer_has_unknown_payment_state():
    payment = build(USD_INVOICE)["payment"]
    assert payment["method"] == "transfer"
    assert payment["paid"] is None
    assert payment["paid_date"] is None


def test_foreign_currency_leaves_base_amount_for_later():
    doc = build(USD_INVOICE)
    assert doc["totals"]["gross"] == {"amount": "480.00", "currency": "USD"}
    assert doc["totals"]["gross_base"] is None
    assert doc["totals"]["fx"] is None
    assert "foreign_currency" in doc["flags"]
    assert doc["vat_lines"] == [{"rate": "np", "net": "480.00", "vat": "0.00"}]
    assert doc["status"] == "extracted"


def test_unreadable_gross_lands_in_review_with_zero_gross():
    doc = build(UNREADABLE)
    assert doc["totals"]["gross"] == {"amount": "0.00", "currency": "PLN"}
    assert doc["totals"]["gross_base"] is None
    assert doc["seller"]["name"] == "(unreadable)"
    assert doc["extraction"]["confidence"] == 0.0
    assert doc["status"] == "needs_review"
    assert "amount_unclear" in doc["flags"]
    assert "Gross amount not found" in doc["extraction"]["warnings"]


def test_more_than_ten_lines_keeps_ten_and_warns():
    answer = copy.deepcopy(HERO)
    answer["lines"] = [{"description": f"Item {n} (SAMPLE)"} for n in range(12)]
    doc = build(answer)
    assert len(doc["lines"]) == 10
    assert "Only the first 10 of 12 lines were read" in doc["extraction"]["warnings"]


def test_caller_warnings_come_first():
    warnings = build(UNREADABLE, warnings=["Markdown was cut at 24000 characters"])["extraction"]["warnings"]
    assert warnings[0] == "Markdown was cut at 24000 characters"


def test_ocr_score_reaches_the_confidence():
    assert build(HERO, ocr_score=0.6)["extraction"]["confidence"] == 0.6


def test_money_is_normalised_to_two_decimals():
    answer = copy.deepcopy(HERO)
    answer.update(gross="1 299,0", vat="242.9")
    doc = build(answer)
    assert doc["totals"]["gross"]["amount"] == "1299.00"
    assert doc["totals"]["vat"]["amount"] == "242.90"


def test_values_outside_the_contract_are_dropped():
    answer = copy.deepcopy(HERO)
    answer.update(doc_type="bill", payment_method="blik", card_last4="77300", issue_date="20.11.2026")
    answer["seller"] = {**answer["seller"], "country": "Poland"}
    doc = build(answer)
    assert doc["doc_type"] == "other"
    assert doc["payment"]["method"] == "unknown"
    assert doc["payment"]["card_last4"] is None
    assert doc["issue_date"] is None
    assert doc["seller"]["country"] is None
    assert any("is not a date" in w for w in doc["extraction"]["warnings"])
    assert schema_errors(doc) == []


def test_vat_line_net_is_gross_minus_vat_whatever_the_model_wrote():
    answer = copy.deepcopy(HERO)
    answer["vat_lines"] = [{"rate": "23", "net": "1064.71", "vat": "242.90", "gross": "1299.00"}]
    doc = build(answer)
    assert doc["vat_lines"] == [{"rate": "23", "net": "1056.10", "vat": "242.90"}]
    assert doc["status"] == "extracted"


def test_net_copied_from_gross_is_derived_again():
    answer = copy.deepcopy(HERO)
    answer.update(net="1299.00", vat_lines=[{"rate": "23", "net": "1299.00", "vat": "242.90", "gross": None}])
    doc = build(answer)
    assert doc["totals"]["net"]["amount"] == "1056.10"
    assert doc["vat_lines"] == [{"rate": "23", "net": "1056.10", "vat": "242.90"}]
    assert doc["status"] == "extracted"
    assert doc["extraction"]["warnings"] == []


def test_net_equal_to_gross_stays_when_there_is_no_vat():
    doc = build(USD_INVOICE)
    assert doc["totals"]["net"]["amount"] == "480.00"


def test_incomplete_vat_lines_are_dropped():
    answer = copy.deepcopy(HERO)
    answer["vat_lines"] = [{"rate": "23", "vat": None, "gross": "1299.00"},
                           {"rate": "8", "vat": "8.00", "gross": None}]
    assert build(answer)["vat_lines"] == []


def test_single_vat_line_without_gross_takes_the_document_gross():
    answer = copy.deepcopy(HERO)
    answer["vat_lines"] = [{"rate": "23", "vat": "242.90", "gross": None}]
    doc = build(answer)
    assert doc["vat_lines"] == [{"rate": "23", "net": "1056.10", "vat": "242.90"}]
    assert doc["status"] == "extracted"


def test_category_is_left_to_the_matcher():
    assert build(HERO)["category_suggestion"] is None
