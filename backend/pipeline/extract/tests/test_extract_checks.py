from dataclasses import replace
from datetime import date

import pytest

from backend.pipeline.extract.checks import (
    Reading,
    VatLine,
    assess,
    nip_valid,
    normalise_vat_rate,
    start_confidence,
)

TODAY = date(2026, 11, 21)
FIELDS = {"gross": 0.99, "net": 0.95, "vat": 0.97, "issue_date": 0.95, "seller_tax_id": 0.97}

HERO = Reading(
    gross="1299.00",
    net="1056.10",
    vat="242.90",
    currency="PLN",
    issue_date="2026-11-20",
    seller_tax_id="9990000043",
    vat_lines=(VatLine("23", "1056.10", "242.90"),),
)


def run(reading=HERO, self_report=0.95, fields=None, ocr_score=None):
    return assess(reading, self_report=self_report, field_confidence=dict(fields or FIELDS),
                  ocr_score=ocr_score, today=TODAY)


def test_start_is_the_lower_of_self_report_and_ocr_score():
    assert start_confidence(0.95, ocr_score=0.7) == 0.7
    assert start_confidence(0.6, ocr_score=0.9) == 0.6


def test_start_without_ocr_score_is_the_self_report():
    assert start_confidence(0.88) == 0.88


def test_start_takes_the_gross_field_confidence_when_lower():
    assert start_confidence(0.95, gross_confidence=0.5, ocr_score=0.9) == 0.5


def test_start_is_clamped_to_zero_and_one():
    assert start_confidence(1.4) == 1.0
    assert start_confidence(-0.2) == 0.0


def test_ocr_score_lowers_the_document_confidence():
    result = run(ocr_score=0.7)
    assert result.confidence == 0.7
    assert result.status == "needs_review"
    assert "low_confidence" in result.flags


def test_clean_receipt_is_extracted_with_its_start_confidence():
    result = run()
    assert result.confidence == 0.95
    assert result.status == "extracted"
    assert result.warnings == []
    assert result.flags == []
    assert result.field_confidence == FIELDS


def test_net_plus_vat_not_gross_fails_an_amount_check():
    result = run(replace(HERO, gross="1299.50"))
    assert result.confidence == pytest.approx(0.95 * 0.6)
    assert result.status == "needs_review"
    assert "amount_unclear" in result.flags
    assert any("does not equal gross" in w for w in result.warnings)
    assert result.field_confidence["gross"] == pytest.approx(0.99 * 0.6)
    assert result.field_confidence["seller_tax_id"] == 0.97


def test_sum_within_two_grosze_passes():
    result = run(replace(HERO, gross="1299.02", vat_lines=(VatLine("23", "1056.10", "242.90"),)))
    assert not any("does not equal gross" in w for w in result.warnings)


def test_vat_lines_not_adding_up_to_total_vat_fail_an_amount_check():
    lines = (VatLine("23", "1000.00", "230.00"), VatLine("8", "56.10", "4.49"))
    result = run(replace(HERO, vat_lines=lines))
    assert result.status == "needs_review"
    assert "amount_unclear" in result.flags
    assert any("VAT lines add up to" in w for w in result.warnings)


def test_vat_that_is_not_the_rate_of_net_fails_an_amount_check():
    misread = replace(HERO, gross="1239.00", net="996.10", vat_lines=(VatLine("23", "996.10", "242.90"),))
    result = run(misread)
    assert result.status == "needs_review"
    assert "amount_unclear" in result.flags
    assert any("is not 23% of net" in w for w in result.warnings)


def test_rate_math_is_skipped_for_exempt_and_reverse_charge_lines():
    reading = replace(HERO, gross="1000.00", net="1000.00", vat="0.00", currency="USD", seller_tax_id="US-123",
                      vat_lines=(VatLine("np", "1000.00", "0.00"),))
    result = run(reading)
    assert "amount_unclear" not in result.flags
    assert result.status == "extracted"


def test_bad_nip_checksum_fails_and_lowers_the_seller_tax_id():
    result = run(replace(HERO, seller_tax_id="9990000044"))
    assert result.confidence == pytest.approx(0.95 * 0.6)
    assert result.field_confidence["seller_tax_id"] == pytest.approx(0.97 * 0.6)
    assert any("NIP checksum" in w for w in result.warnings)
    assert result.status == "needs_review"
    assert "amount_unclear" not in result.flags


def test_nip_checksum_accepts_prefix_spaces_and_dashes():
    assert nip_valid("9990000043") is True
    assert nip_valid("PL 999-000-00-43") is True
    assert nip_valid("9990000044") is False


def test_foreign_tax_ids_are_not_checked():
    assert nip_valid("DE123456789") is None
    assert nip_valid("US-12-3456789") is None
    assert run(replace(HERO, seller_tax_id="DE123456789")).status == "extracted"


@pytest.mark.parametrize("issue_date, warning", [
    ("2025-10-16", "more than 400 days old"),
    ("2026-11-23", "in the future"),
    (None, "No issue date found"),
    ("20.11.2026", "is not a date"),
])
def test_dates_outside_the_window_or_missing_fail(issue_date, warning):
    result = run(replace(HERO, issue_date=issue_date))
    assert result.confidence == pytest.approx(0.95 * 0.6)
    assert result.field_confidence["issue_date"] == pytest.approx(0.95 * 0.6)
    assert any(warning in w for w in result.warnings)


@pytest.mark.parametrize("issue_date", ["2025-10-17", "2026-11-22"])
def test_dates_on_the_window_edges_pass(issue_date):
    assert run(replace(HERO, issue_date=issue_date)).status == "extracted"


def test_odd_vat_rate_fails():
    reading = replace(HERO, vat_lines=(VatLine("7", "1056.10", "242.90"),))
    result = run(reading)
    assert any("not a Polish VAT rate" in w for w in result.warnings)
    assert result.field_confidence["vat"] < 0.97


@pytest.mark.parametrize("rate", ["23", "8", "5", "0", "zw", "np", "oo", "np I", "23%", "8.00"])
def test_polish_vat_rates_pass(rate):
    reading = Reading(gross="100.00", currency="PLN", issue_date="2026-11-20", seller_tax_id="9990000043",
                      vat_lines=(VatLine(rate, None, None),))
    assert not any("VAT rate" in w for w in run(reading).warnings)


@pytest.mark.parametrize("raw, normalised", [("np I", "np"), ("NP II", "np"), ("23%", "23"), ("8.00", "8"),
                                             ("5,0", "5"), (" zw ", "zw"), ("7.5", "7.5")])
def test_vat_rate_normalisation(raw, normalised):
    assert normalise_vat_rate(raw) == normalised


def test_unrecognised_currency_fails():
    result = run(replace(HERO, currency="XYZ"))
    assert any("Currency XYZ is not recognised" in w for w in result.warnings)
    assert result.confidence == pytest.approx(0.95 * 0.6)


def test_missing_currency_fails():
    result = run(replace(HERO, currency=None))
    assert any("No currency found" in w for w in result.warnings)
    assert "foreign_currency" not in result.flags


def test_foreign_currency_is_flagged_but_not_penalised():
    result = run(replace(HERO, currency="eur"))
    assert "foreign_currency" in result.flags
    assert result.confidence == 0.95


def test_missing_seller_tax_id_flags_and_warns_without_penalty():
    result = run(replace(HERO, seller_tax_id=None))
    assert "missing_tax_id" in result.flags
    assert "No seller tax id found" in result.warnings
    assert result.confidence == 0.95
    assert result.status == "extracted"


def test_each_failure_multiplies_again():
    result = run(replace(HERO, seller_tax_id="9990000044", currency="XYZ"))
    assert result.confidence == pytest.approx(0.95 * 0.6 * 0.6)
    assert len(result.warnings) == 2


def test_missing_gross_is_zero_confidence_and_needs_review():
    result = run(replace(HERO, gross=None))
    assert result.confidence == 0.0
    assert result.field_confidence["gross"] == 0.0
    assert result.status == "needs_review"
    assert "amount_unclear" in result.flags
    assert "low_confidence" in result.flags
    assert "Gross amount not found" in result.warnings
