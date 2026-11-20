import argparse
import json
import re
import sys
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import ExtractionError, docling, model, run

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
}
BUDGET_SECONDS = 10.0


def load_truth(paths: list[str]) -> dict[str, tuple[str, str]]:
    truth = {}
    for path in paths:
        for record in json.loads(Path(path).read_text(encoding="utf-8")):
            gross = (record.get("totals") or {}).get("gross")
            if isinstance(gross, dict):
                truth[record["id"]] = (_cents(gross.get("amount")), gross.get("currency"))
            elif gross is not None:
                truth[record["id"]] = (_cents(gross), record.get("currency"))
    return truth


def truth_id(path: Path) -> str:
    return re.sub(r"-\d+$", "", path.stem)


def verdict(status: str | None, gross: tuple[str | None, str | None], expected: tuple[str, str] | None) -> str:
    if status is None:
        return "ERROR"
    if status == "needs_review":
        return "review"
    if expected is None:
        return "-"
    return "ok" if gross == expected else "WRONG"


def bench_file(path: Path, truth: dict[str, tuple[str, str]], today: date | None,
               docling_client: Any, llm_client: Any) -> dict[str, Any]:
    key = truth_id(path)
    expected = truth.get(key)
    record: dict[str, Any] = {"file": str(path), "truth_id": key if expected else None,
                              "expected": list(expected) if expected else None}
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    started = time.monotonic()
    try:
        if content_type is None:
            raise ExtractionError(f"no content type for {path.suffix!r}")
        result = run(path.read_bytes(), content_type, today=today, docling_client=docling_client,
                     llm_client=llm_client)
    except ExtractionError as error:
        record.update(total_seconds=round(time.monotonic() - started, 2), status=None, verdict="ERROR",
                      error=str(error))
        return record
    document = result.document
    gross = document["totals"]["gross"]
    extracted = (_cents(gross["amount"]), gross["currency"])
    record.update(
        docling_seconds=round(result.docling_seconds, 2),
        model_seconds=round(result.model_seconds, 2),
        total_seconds=round(time.monotonic() - started, 2),
        gross=list(extracted),
        gross_correct=(extracted == expected) if expected else None,
        status=document["status"],
        verdict=verdict(document["status"], extracted, expected),
        confidence=document["extraction"]["confidence"],
        flags=document["flags"],
        warnings=document["extraction"]["warnings"],
        error=None,
        document=document,
        markdown=result.markdown,
    )
    return record


def row(record: dict[str, Any]) -> str:
    gross = " ".join(record["gross"]) if record.get("gross") else "-"
    expected = " ".join(record["expected"]) if record.get("expected") else "-"
    note = record["error"] or "; ".join(record.get("warnings") or [])
    return (f"{Path(record['file']).name:<24} {_seconds(record.get('docling_seconds')):>7} "
            f"{_seconds(record.get('model_seconds')):>7} {_seconds(record.get('total_seconds')):>7} "
            f"{gross:>14} {expected:>14} {record['verdict']:<7} {_score(record.get('confidence')):>5}  {note}")


def summary(records: list[dict[str, Any]]) -> str:
    counts = {name: sum(r["verdict"] == name for r in records) for name in ("ok", "review", "WRONG", "ERROR", "-")}
    with_truth = sum(r["truth_id"] is not None for r in records)
    totals = [r["total_seconds"] for r in records if r["verdict"] != "ERROR"]
    slow = sum(t > BUDGET_SECONDS for t in totals)
    timing = (f"max total {max(totals):.1f} s, mean {sum(totals) / len(totals):.1f} s, "
              f"over {BUDGET_SECONDS:.0f} s: {slow}") if totals else "no timings"
    return (f"ok {counts['ok']}/{with_truth}, review {counts['review']}, wrong {counts['WRONG']}, "
            f"errors {counts['ERROR']}, no truth {counts['-']}; {timing}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.pipeline.extract.bench")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--truth", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)

    truth = load_truth(args.truth)
    docling_client = docling.default_client()
    llm_client = model.default_client()
    print(f"{'file':<24} {'docling':>7} {'model':>7} {'total':>7} {'gross':>14} {'expected':>14} "
          f"{'verdict':<7} {'conf':>5}  warnings")
    records = []
    try:
        for path in args.files:
            record = bench_file(path, truth, args.today, docling_client, llm_client)
            records.append(record)
            print(row(record), flush=True)
            if args.markdown and record.get("markdown") is not None:
                print(f"----- {Path(record['file']).name} markdown -----\n{record['markdown']}\n-----", flush=True)
    finally:
        docling_client.close()
    print(summary(records))
    if args.out:
        args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(r["verdict"] in ("WRONG", "ERROR") for r in records) else 0


def _cents(value: Any) -> str | None:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


def _seconds(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "-"


def _score(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


if __name__ == "__main__":
    sys.exit(main())
