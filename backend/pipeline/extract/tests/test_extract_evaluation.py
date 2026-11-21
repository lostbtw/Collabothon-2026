import json
from pathlib import Path

import pytest

from backend.pipeline.extract import evaluation
from backend.pipeline.extract.evaluation import Case, Truth
from backend.pipeline.extract.tests.test_extract_document import HERO
from backend.pipeline.extract.tests.test_extract_pipeline import JPEG, TODAY, FakeDocling, FakeModel

REPO = Path(__file__).resolve().parents[4]
NOVEMBER = REPO / "sim" / "scenario" / "out" / "november_documents.json"
RECEIPTS = REPO / "sim" / "documents" / "receipts" / "receipts_truth.json"
DOCUMENTS = REPO / "sim" / "documents"

HERO_TRUTH = Truth(gross="1299.00", currency="PLN", issue_date="2026-11-20", seller_tax_id="9990000043",
                   vat="242.90")


def outputs(status="extracted", **changes):
    read = {"gross": "1299.00", "currency": "PLN", "issue_date": "2026-11-20", "seller_tax_id": "9990000043",
            "vat": "242.90", "status": status, "confidence": 0.9, "warnings": [], "flags": [],
            "docling_seconds": 3.0, "model_seconds": 2.0, "total_seconds": 5.0, "trace_id": None, "error": None}
    return {**read, **changes}


def row(case_id="rcpt_hero-1", subset="real_photo", status="extracted", **changes):
    return evaluation.score(Case(case_id, Path(f"{case_id}.jpg"), subset, HERO_TRUTH), outputs(status, **changes))


def test_the_november_set_loads_all_four_fields_and_finds_every_file():
    cases = evaluation.load_november(NOVEMBER, DOCUMENTS)

    assert len(cases) == 47
    assert {case.subset for case in cases} == {"text_pdf", "rendered_photo"}
    assert all(case.path.is_file() for case in cases)
    first = next(case for case in cases if case.case_id == "nov_001")
    assert first.truth == Truth(gross="2460.00", currency="PLN", issue_date="2026-11-01",
                                seller_tax_id="9990010001", vat="460.00")


def test_receipt_photos_take_the_truth_of_their_receipt(tmp_path):
    for name in ("rcpt_hero-1.jpg", "rcpt_cafe-2.JPG", "notes.txt"):
        (tmp_path / name).write_bytes(JPEG)

    cases = evaluation.load_receipt_photos(RECEIPTS, tmp_path)

    assert [(case.case_id, case.subset) for case in cases] == [("rcpt_cafe-2", "real_photo"),
                                                               ("rcpt_hero-1", "real_photo")]
    assert cases[1].truth == HERO_TRUTH


def test_renders_of_the_printed_receipts_are_their_own_subset(tmp_path):
    (tmp_path / "rcpt_office-4.jpg").write_bytes(JPEG)

    cases = evaluation.load_receipt_photos(RECEIPTS, tmp_path, subset="receipt_render")

    assert [(case.case_id, case.subset, case.truth.gross) for case in cases] == [
        ("rcpt_office-4", "receipt_render", "238.98")]


def test_the_committed_receipt_renders_all_have_truth():
    cases = evaluation.load_receipt_photos(RECEIPTS, REPO / "notebooks" / "receipt_renders", subset="receipt_render")

    assert len(cases) == 12
    assert {case.case_id.rsplit("-", 1)[0] for case in cases} == {"rcpt_hero", "rcpt_cafe", "rcpt_office"}


def test_headline_counts_rendered_photos_without_calling_them_real():
    rows = [row("nov_003", "rendered_photo"), row("rcpt_cafe-1", "receipt_render", gross="47.00")]

    first_line = evaluation.headline(rows).splitlines()[0]

    assert first_line.startswith("Gross amount read right on 1 of 2 documents, 1 of 2 photos;")
    assert "real" not in first_line


def test_a_photo_without_truth_is_refused(tmp_path):
    (tmp_path / "rcpt_unknown-1.jpg").write_bytes(JPEG)

    with pytest.raises(ValueError, match="rcpt_unknown"):
        evaluation.load_receipt_photos(RECEIPTS, tmp_path)


def test_no_photo_folder_yet_means_no_photo_cases(tmp_path):
    assert evaluation.load_receipt_photos(RECEIPTS, tmp_path / "missing") == []


def test_truth_reads_money_as_strings_or_as_amount_and_currency():
    scenario = {"currency": "USD", "issue_date": "2026-11-07", "seller": {"tax_id": "EIN 99-0000101"},
                "totals": {"gross": "120", "vat": "0.00"}}
    receipt = {"issue_date": "2026-11-20", "seller": {"tax_id": "9990000043"},
               "totals": {"gross": {"amount": "1299.00", "currency": "PLN"},
                          "vat": {"amount": "242.90", "currency": "PLN"}}}

    assert evaluation.truth_of(scenario) == Truth("120.00", "USD", "2026-11-07", "EIN 99-0000101", "0.00")
    assert evaluation.truth_of(receipt) == HERO_TRUTH


def test_a_correct_reading_is_right_on_every_field():
    assert evaluation.compare(outputs(), HERO_TRUTH) == dict.fromkeys(evaluation.FIELDS, True)


@pytest.mark.parametrize("read, truth", [
    ("PL 999-000-00-43", "9990000043"),
    ("NIP: 999 000 00 43", "9990000043"),
    ("99-0000101", "EIN 99-0000101"),
    ("nl999999101b01", "NL999999101B01"),
])
def test_tax_ids_match_without_spacing_labels_or_the_pl_prefix(read, truth):
    assert evaluation.normalise_tax_id(read) == evaluation.normalise_tax_id(truth)


def test_a_different_tax_id_is_wrong():
    assert evaluation.compare(outputs(seller_tax_id="9990000044"), HERO_TRUTH)["seller_tax_id"] is False


def test_gross_in_another_currency_is_wrong():
    assert evaluation.compare(outputs(currency="EUR"), HERO_TRUTH)["gross"] is False


def test_gross_is_compared_to_the_cent():
    assert evaluation.compare(outputs(gross="1299"), HERO_TRUTH)["gross"] is True
    assert evaluation.compare(outputs(gross="1239.00"), HERO_TRUTH)["gross"] is False


@pytest.mark.parametrize("read, truth, right", [
    (None, "0.00", True),
    ("0.00", "0.00", True),
    (None, "242.90", False),
    ("24.29", "242.90", False),
])
def test_vat_not_read_counts_as_zero_and_nothing_else(read, truth, right):
    case_truth = Truth("1299.00", "PLN", "2026-11-20", "9990000043", truth)

    assert evaluation.compare(outputs(vat=read), case_truth)["vat"] is right


def test_a_failed_read_is_wrong_on_every_field():
    failed = evaluation.failed("docling-serve unreachable", 1.0)

    assert evaluation.compare(failed, HERO_TRUTH) == dict.fromkeys(evaluation.FIELDS, False)


def test_a_wrong_field_is_silently_wrong_only_when_the_document_was_accepted():
    assert row(gross="1239.00")["silently_wrong"] == ["gross"]
    assert row(status="needs_review", gross="1239.00")["silently_wrong"] == []
    assert row(status=None, error="model down")["silently_wrong"] == []


def test_read_case_runs_the_real_extraction_path(tmp_path):
    path = tmp_path / "rcpt_hero-1.jpg"
    path.write_bytes(JPEG)

    read = evaluation.read_case(path, today=TODAY, docling_client=FakeDocling().client(),
                                llm_client=FakeModel(HERO))

    assert evaluation.compare(read, HERO_TRUTH) == dict.fromkeys(evaluation.FIELDS, True)
    assert read["status"] == "extracted"
    assert read["error"] is None
    assert read["total_seconds"] >= read["docling_seconds"]


def test_read_case_turns_a_failed_extraction_into_an_error_row(tmp_path):
    path = tmp_path / "rcpt_hero-1.jpg"
    path.write_bytes(JPEG)

    read = evaluation.read_case(path, today=TODAY, docling_client=FakeDocling().client(),
                                llm_client=FakeModel(error=RuntimeError("model down")))

    assert read["status"] is None
    assert "model down" in read["error"]


def test_read_case_refuses_an_unknown_file_type(tmp_path):
    path = tmp_path / "scan.heic"
    path.write_bytes(b"sample")

    assert ".heic" in evaluation.read_case(path)["error"]


def test_summary_has_accuracy_silently_wrong_review_and_latency_per_subset():
    rows = [row("nov_001", "text_pdf"),
            row("nov_003", "rendered_photo", status="needs_review", gross="1239.00", total_seconds=12.0),
            row("rcpt_hero-1", "real_photo", vat="24.29"),
            row("rcpt_hero-2", "real_photo", status=None, error="model down", total_seconds=1.0)]

    metrics = evaluation.summarise(rows)

    assert metrics["all/documents"] == 4
    assert metrics["all/gross_accuracy"] == 0.5
    assert metrics["all/vat_accuracy"] == 0.5
    assert metrics["all/vat_silently_wrong"] == 1
    assert metrics["all/gross_silently_wrong"] == 0
    assert metrics["all/needs_review_rate"] == 0.25
    assert metrics["all/errors"] == 1
    assert metrics["all/total_seconds_max"] == 12.0
    assert metrics["all/over_budget"] == 1
    assert metrics["real_photo/documents"] == 2
    assert metrics["rendered_photo/gross_accuracy"] == 0.0


def test_a_subset_without_rows_has_no_metrics():
    metrics = evaluation.summarise([row("nov_001", "text_pdf")])

    assert not any(key.startswith("real_photo/") for key in metrics)


def test_headline_leads_with_gross_and_real_photos_and_names_nothing_silently_wrong():
    rows = [row("nov_001", "text_pdf"), row("rcpt_hero-1"), row("rcpt_hero-2", status="needs_review", gross="1239.00")]

    assert evaluation.headline(rows) == (
        "Gross amount read right on 2 of 3 documents, 1 of 2 photos, 1 of 2 real phone photos; "
        "none silently wrong.\n"
        "Date 3/3, seller NIP 3/3, VAT 3/3; 1 of 3 sent to review.")


def test_headline_names_every_silently_wrong_field():
    rows = [row("nov_001", "text_pdf", vat="24.29", issue_date="2026-11-02")]

    first_line = evaluation.headline(rows).splitlines()[0]

    assert first_line == ("Gross amount read right on 1 of 1 documents; "
                          "2 silently wrong (date on nov_001, VAT on nov_001).")


def test_headline_names_the_first_five_silently_wrong_fields_and_counts_the_rest():
    rows = [row(f"nov_00{n}", "text_pdf", vat="24.29") for n in range(1, 8)]

    first_line = evaluation.headline(rows).splitlines()[0]

    assert first_line.endswith("7 silently wrong (VAT on nov_001, VAT on nov_002, VAT on nov_003, VAT on nov_004, "
                               "VAT on nov_005 and 2 more).")


def test_the_score_row_is_json_ready_for_the_notebook_table():
    scored = row(gross="1239.00")

    assert json.loads(json.dumps(scored))["gross_read"] == "1239.00 PLN"
    assert scored["gross_truth"] == "1299.00 PLN"
