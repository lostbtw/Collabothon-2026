"""Prepares real phone photos of the printed SAMPLE receipts for the evaluation notebook (#19).

    uv run --with pillow --with pillow-heif python notebooks/strip_exif.py rcpt_hero IMG_0412.HEIC IMG_0413.jpg

For each photo: turn it upright as the phone's EXIF orientation says, drop all metadata (EXIF with GPS
position and device, XMP, ICC), cap the longest side at 2048 px (about what a forwarded phone photo
delivers) and save it as JPEG quality 90 under notebooks/receipt_photos/<truth id>-<n>.jpg, numbered
after the photos already there. The truth id must be one of sim/documents/receipts/receipts_truth.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parents[1]
TRUTH = REPO / "sim" / "documents" / "receipts" / "receipts_truth.json"
OUT = REPO / "notebooks" / "receipt_photos"
LONGEST_SIDE = 2048
QUALITY = 90


def truth_ids() -> set[str]:
    return {record["id"] for record in json.loads(TRUTH.read_text(encoding="utf-8"))}


def next_number(out: Path, truth_id: str) -> int:
    taken = [int(match.group(1)) for path in out.glob(f"{truth_id}-*.jpg")
             if (match := re.fullmatch(rf"{re.escape(truth_id)}-(\d+)", path.stem))]
    return max(taken, default=0) + 1


def clean(source: Path, target: Path) -> tuple[int, int]:
    with Image.open(source) as image:
        upright = ImageOps.exif_transpose(image).convert("RGB")
    upright.thumbnail((LONGEST_SIDE, LONGEST_SIDE), Image.Resampling.LANCZOS)
    pixels = Image.new("RGB", upright.size)
    pixels.paste(upright)
    pixels.save(target, "JPEG", quality=QUALITY, optimize=True)
    with Image.open(target) as written:
        if written.getexif() or written.info.get("icc_profile") or written.info.get("xmp"):
            raise RuntimeError(f"{target.name} still carries metadata")
    return pixels.size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("truth_id")
    parser.add_argument("photos", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    known = truth_ids()
    if args.truth_id not in known:
        parser.error(f"unknown truth id {args.truth_id!r}; known: {', '.join(sorted(known))}")
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        if any(path.suffix.lower() in (".heic", ".heif") for path in args.photos):
            parser.error("HEIC photos need pillow-heif: add --with pillow-heif")

    args.out.mkdir(parents=True, exist_ok=True)
    number = next_number(args.out, args.truth_id)
    for source in args.photos:
        target = args.out / f"{args.truth_id}-{number}.jpg"
        width, height = clean(source, target)
        print(f"{source.name} -> {target.relative_to(REPO) if target.is_relative_to(REPO) else target} "
              f"({width}x{height}, no metadata)")
        number += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
