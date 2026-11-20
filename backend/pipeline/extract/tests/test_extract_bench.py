import copy
import json
from pathlib import Path

import pytest

from backend.pipeline.extract import bench
from backend.pipeline.extract.tests.test_extract_document import HERO
from backend.pipeline.extract.tests.test_extract_pipeline import FakeDocling, FakeModel

REPO = Path(__file__).resolve().parents[4]
NOVEMBER = REPO / "sim" / "scenario" / "out" / "november_documents.json"
RECEIPTS = REPO / "sim" / "documents" / "receipts" / "receipts_truth.json"


def test_truth_reads_scenario_and_receipt_formats():
    truth = bench.load_truth([str(NOVEMBER), str(RECEIPTS)])
    assert truth["nov_001"] == ("2460.00", "PLN")
    assert truth["rcpt_hero"] == ("1299.00", "PLN")
    assert truth["doc_rcpt412"] == ("1299.00", "PLN")


@pytest.mark.parametrize("name, key", [("nov_003.jpg", "nov_003"), ("rcpt_hero-2.jpg", "rcpt_hero"),
                                       ("doc_rcpt412.jpg", "doc_rcpt412"), ("nov_001.pdf", "nov_001")])
def test_truth_id_is_the_stem_without_copy_number(name, key):
    assert bench.truth_id(Path(name)) == key


@pytest.mark.parametrize("status, gross, expected, result", [
    ("extracted", ("1299.00", "PLN"), ("1299.00", "PLN"), "ok"),
    ("extracted", ("1239.00", "PLN"), ("1299.00", "PLN"), "WRONG"),
    ("extracted", ("1299.00", "EUR"), ("1299.00", "PLN"), "WRONG"),
    ("needs_review", ("1239.00", "PLN"), ("1299.00", "PLN"), "review"),
    ("extracted", ("1299.00", "PLN"), None, "-"),
    (None, (None, None), ("1299.00", "PLN"), "ERROR"),
])
def test_verdicts(status, gross, expected, result):
    assert bench.verdict(status, gross, expected) == result


def write_photo(tmp_path, name="rcpt_hero-1.jpg"):
    path = tmp_path / name
    path.write_bytes(b"\xff\xd8\xff\xe0 sample photo")
    return path


def test_bench_file_records_times_and_verdict(tmp_path):
    record = bench.bench_file(write_photo(tmp_path), {"rcpt_hero": ("1299.00", "PLN")}, None,
                              FakeDocling().client(), FakeModel(HERO))
    assert record["verdict"] == "ok"
    assert record["gross_correct"] is True
    assert record["truth_id"] == "rcpt_hero"
    assert record["total_seconds"] >= record["docling_seconds"]
    assert record["document"]["status"] == "extracted"


def test_unknown_extension_is_an_error_row(tmp_path):
    path = tmp_path / "scan.heic"
    path.write_bytes(b"sample")
    record = bench.bench_file(path, {}, None, FakeDocling().client(), FakeModel(HERO))
    assert record["verdict"] == "ERROR"
    assert ".heic" in record["error"]


def test_cli_prints_rows_and_summary_and_writes_results(tmp_path, monkeypatch, capsys):
    wrong = copy.deepcopy(HERO)
    wrong.update(gross="1239.00", vat_lines=[{"rate": "23", "net": None, "vat": "231.68", "gross": "1239.00"}],
                 vat="231.68")
    models = FakeModel(HERO, wrong)
    monkeypatch.setattr(bench.docling, "default_client", lambda: FakeDocling().client())
    monkeypatch.setattr(bench.model, "default_client", lambda: models)
    out = tmp_path / "results.json"
    code = bench.main([str(write_photo(tmp_path, "rcpt_hero-1.jpg")), str(write_photo(tmp_path, "rcpt_hero-2.jpg")),
                       "--truth", str(RECEIPTS), "--out", str(out), "--today", "2026-11-21"])
    printed = capsys.readouterr().out
    assert "rcpt_hero-1.jpg" in printed
    assert "ok 1/2, review 0, wrong 1, errors 0, no truth 0" in printed
    assert code == 1
    records = json.loads(out.read_text(encoding="utf-8"))
    assert [r["verdict"] for r in records] == ["ok", "WRONG"]


def test_cli_exits_zero_when_nothing_is_wrong(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench.docling, "default_client", lambda: FakeDocling().client())
    monkeypatch.setattr(bench.model, "default_client", lambda: FakeModel(HERO))
    assert bench.main([str(write_photo(tmp_path)), "--truth", str(RECEIPTS), "--today", "2026-11-21"]) == 0
    assert "over 10 s: 0" in capsys.readouterr().out
