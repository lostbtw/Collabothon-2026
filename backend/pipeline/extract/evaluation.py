"""How accurately Documents are read, measured against Ground truth (#19).

Pure: no MLflow import, so CI tests it without a model. The evaluation notebook
(`notebooks/extraction_eval.ipynb`) runs `read_case` as MLflow's predict function and wraps `compare` in
its scorers.

Counting rules:
- A field is right when the value read equals the Ground truth, whatever the Document's status.
- A field is Silently wrong when it is wrong and the Document was accepted without review (`extracted`).
- A VAT that was not read counts as equal to a Ground truth of 0.00. Any other mismatch is wrong.
- Tax ids are compared without spaces, dashes, dots, a printed label (NIP, EIN, VAT) or the PL prefix.
"""
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from . import Extraction, ExtractionError, run
from .bench import BUDGET_SECONDS, CONTENT_TYPES, _cents, truth_id

FIELDS = ("gross", "issue_date", "seller_tax_id", "vat")
FIELD_NAMES = {"gross": "gross", "issue_date": "date", "seller_tax_id": "seller NIP", "vat": "VAT"}
SUBSETS = ("text_pdf", "rendered_photo", "receipt_render", "real_photo")
PHOTO_SUBSETS = ("rendered_photo", "receipt_render", "real_photo")
NOVEMBER_SUBSETS = {"pdf": "text_pdf", "photo": "rendered_photo"}
PHOTO_SUFFIXES = {".jpg", ".jpeg"}
ZERO = "0.00"
HEADLINE_NAMES = 5
TAX_ID_LABEL = re.compile(r"^(NIP|EIN|VATID|VAT)[:.]?")


@dataclass(frozen=True)
class Truth:
    gross: str | None
    currency: str | None
    issue_date: str | None
    seller_tax_id: str | None
    vat: str | None


@dataclass(frozen=True)
class Case:
    case_id: str
    path: Path
    subset: str
    truth: Truth


def load_november(truth_path: Path, documents_dir: Path) -> list[Case]:
    """Role 4's November documents; `artefact` paths are relative to `sim/documents/`."""
    cases = []
    for record in _read(truth_path):
        subset = NOVEMBER_SUBSETS.get(record.get("format"))
        if subset is None:
            raise ValueError(f"{record['id']}: unknown format {record.get('format')!r}")
        cases.append(Case(record["id"], documents_dir / record["artefact"], subset, truth_of(record)))
    return cases


def load_receipt_photos(truth_path: Path, photos_dir: Path, subset: str = "real_photo") -> list[Case]:
    """Photos of the printed receipts named `<truth id>-<n>.jpg`: real phone photos, or renders of the printed
    layout (`receipt_render`). No folder is an empty list; a photo without truth is an error."""
    if not photos_dir.is_dir():
        return []
    truths = {record["id"]: truth_of(record) for record in _read(truth_path)}
    cases = []
    for path in sorted(p for p in photos_dir.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES):
        key = truth_id(path)
        if key not in truths:
            raise ValueError(f"{path.name}: no ground truth for {key!r} in {truth_path.name}")
        cases.append(Case(path.stem, path, subset, truths[key]))
    return cases


def truth_of(record: dict[str, Any]) -> Truth:
    """Money as a string with a top-level currency (scenario) or as {amount, currency} (receipts)."""
    totals = record.get("totals") or {}
    gross, currency = _money(totals.get("gross"))
    vat, _ = _money(totals.get("vat"))
    return Truth(gross=gross, currency=currency or record.get("currency"), issue_date=record.get("issue_date"),
                 seller_tax_id=(record.get("seller") or {}).get("tax_id"), vat=vat)


def read_case(path: Path, *, today: date | None = None, docling_client: Any = None,
              llm_client: Any = None) -> dict[str, Any]:
    """Reads one file the way the extractor does; a failed read is a row with an error, not an exception."""
    started = time.monotonic()
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    try:
        if content_type is None:
            raise ExtractionError(f"no content type for {path.suffix!r}")
        extraction = run(path.read_bytes(), content_type, today=today, docling_client=docling_client,
                         llm_client=llm_client)
    except ExtractionError as error:
        return failed(str(error), time.monotonic() - started)
    return outputs_of(extraction, time.monotonic() - started)


def outputs_of(extraction: Extraction, seconds: float) -> dict[str, Any]:
    document = extraction.document
    gross = document["totals"]["gross"] or {}
    vat = document["totals"]["vat"] or {}
    return {
        "gross": gross.get("amount"),
        "currency": gross.get("currency"),
        "issue_date": document["issue_date"],
        "seller_tax_id": document["seller"]["tax_id"],
        "vat": vat.get("amount"),
        "status": document["status"],
        "confidence": document["extraction"]["confidence"],
        "warnings": document["extraction"]["warnings"],
        "flags": document["flags"],
        "docling_seconds": round(extraction.docling_seconds, 2),
        "model_seconds": round(extraction.model_seconds, 2),
        "total_seconds": round(seconds, 2),
        "trace_id": document["extraction"]["trace_id"],
        "error": None,
    }


def failed(error: str, seconds: float) -> dict[str, Any]:
    return {"gross": None, "currency": None, "issue_date": None, "seller_tax_id": None, "vat": None,
            "status": None, "confidence": None, "warnings": [], "flags": [], "docling_seconds": None,
            "model_seconds": None, "total_seconds": round(seconds, 2), "trace_id": None, "error": error}


def compare(outputs: dict[str, Any], truth: Truth) -> dict[str, bool]:
    if outputs.get("status") is None:
        return dict.fromkeys(FIELDS, False)
    return {
        "gross": (_cents(outputs.get("gross")), outputs.get("currency")) == (truth.gross, truth.currency),
        "issue_date": outputs.get("issue_date") == truth.issue_date,
        "seller_tax_id": normalise_tax_id(outputs.get("seller_tax_id")) == normalise_tax_id(truth.seller_tax_id),
        "vat": _vat_equal(_cents(outputs.get("vat")), truth.vat),
    }


def silently_wrong(outputs: dict[str, Any], verdicts: dict[str, bool]) -> list[str]:
    if outputs.get("status") != "extracted":
        return []
    return [field for field in FIELDS if not verdicts[field]]


def normalise_tax_id(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[\s\-.]", "", str(value)).upper()
    text = TAX_ID_LABEL.sub("", text).removeprefix("PL")
    return text or None


def score(case: Case, outputs: dict[str, Any]) -> dict[str, Any]:
    """One row of the per-document table: what was read, what is true, and the verdicts."""
    verdicts = compare(outputs, case.truth)
    return {
        "case_id": case.case_id,
        "subset": case.subset,
        "file": case.path.name,
        "status": outputs.get("status"),
        "confidence": outputs.get("confidence"),
        **{f"{field}_ok": verdicts[field] for field in FIELDS},
        "silently_wrong": silently_wrong(outputs, verdicts),
        **{f"{field}_read": read_text(outputs, field) for field in FIELDS},
        **{f"{field}_truth": truth_text(case.truth, field) for field in FIELDS},
        "docling_seconds": outputs.get("docling_seconds"),
        "model_seconds": outputs.get("model_seconds"),
        "total_seconds": outputs.get("total_seconds"),
        "trace_id": outputs.get("trace_id"),
        "error": outputs.get("error"),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Flat metrics for the whole set (`all/...`) and for each subset that has rows."""
    metrics: dict[str, float] = {}
    for scope in ("all", *SUBSETS):
        chosen = rows if scope == "all" else [row for row in rows if row["subset"] == scope]
        if not chosen:
            continue
        count = len(chosen)
        metrics[f"{scope}/documents"] = count
        for field in FIELDS:
            metrics[f"{scope}/{field}_accuracy"] = round(sum(row[f"{field}_ok"] for row in chosen) / count, 4)
            metrics[f"{scope}/{field}_silently_wrong"] = sum(field in row["silently_wrong"] for row in chosen)
        metrics[f"{scope}/needs_review_rate"] = round(sum(row["status"] == "needs_review" for row in chosen) / count, 4)
        metrics[f"{scope}/errors"] = sum(row["error"] is not None for row in chosen)
        timed = [row for row in chosen if row["error"] is None and row["total_seconds"] is not None]
        if timed:
            totals = [row["total_seconds"] for row in timed]
            metrics[f"{scope}/total_seconds_mean"] = round(mean(totals), 2)
            metrics[f"{scope}/total_seconds_max"] = round(max(totals), 2)
            metrics[f"{scope}/docling_seconds_mean"] = round(mean(row["docling_seconds"] for row in timed), 2)
            metrics[f"{scope}/model_seconds_mean"] = round(mean(row["model_seconds"] for row in timed), 2)
            metrics[f"{scope}/over_budget"] = sum(total > BUDGET_SECONDS for total in totals)
    return metrics


def headline(rows: list[dict[str, Any]]) -> str:
    """The pitch number: gross first, then photos (and real phone photos, when there are any), Silently wrong
    fields; then the other fields."""
    count = len(rows)
    parts = [f"Gross amount read right on {_right(rows, 'gross')} of {count} documents"]
    for label, subsets in (("photos", PHOTO_SUBSETS), ("real phone photos", ("real_photo",))):
        chosen = [row for row in rows if row["subset"] in subsets]
        if chosen:
            parts.append(f"{_right(chosen, 'gross')} of {len(chosen)} {label}")
    wrong = [(row["case_id"], field) for row in rows for field in row["silently_wrong"]]
    if wrong:
        named = ", ".join(f"{FIELD_NAMES[field]} on {case_id}" for case_id, field in wrong[:HEADLINE_NAMES])
        more = f" and {len(wrong) - HEADLINE_NAMES} more" if len(wrong) > HEADLINE_NAMES else ""
        verdict = f"{len(wrong)} silently wrong ({named}{more})"
    else:
        verdict = "none silently wrong"
    breakdown = ", ".join(f"{FIELD_NAMES[field]} {_right(rows, field)}/{count}" for field in FIELDS[1:])
    review = sum(row["status"] == "needs_review" for row in rows)
    return (f"{', '.join(parts)}; {verdict}.\n"
            f"{breakdown[0].upper()}{breakdown[1:]}; {review} of {count} sent to review.")


def _right(rows: list[dict[str, Any]], field: str) -> int:
    return sum(row[f"{field}_ok"] for row in rows)


def _vat_equal(read: str | None, truth: str | None) -> bool:
    if read is None and truth == ZERO:
        return True
    return read == truth


def read_text(outputs: dict[str, Any], field: str) -> str | None:
    if field == "gross" and outputs.get("gross") is not None:
        return f"{outputs['gross']} {outputs.get('currency')}"
    return outputs.get(field)


def truth_text(truth: Truth, field: str) -> str | None:
    if field == "gross" and truth.gross is not None:
        return f"{truth.gross} {truth.currency}"
    return getattr(truth, field)


def _money(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        return _cents(value.get("amount")), value.get("currency")
    return _cents(value), None


def _read(path: Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
