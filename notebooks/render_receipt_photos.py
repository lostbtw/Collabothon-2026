"""Renders phone-style photos of the printable SAMPLE receipts for the evaluation notebook (#19).

    CHROME=$(which google-chrome) python notebooks/render_receipt_photos.py

No real phone photos of the printed receipts exist, so this stands in for them. It reuses role 3's code
without changing it: the print layout of `sim/documents/receipts/receipts.py` (the same receipt that is
printed) and the phone-photo effects of `sim/documents/render_november.py` (desk, tilt, noise and the
scenario's defects). Each receipt is rendered four times with different defects, seeded by file name,
so the set is reproducible. Writes notebooks/receipt_renders/<truth id>-<n>.jpg; their Ground truth is
sim/documents/receipts/receipts_truth.json. Needs Pillow and a headless Chrome, Chromium or Edge.
"""
import importlib.util
import json
import random
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECEIPTS = REPO / "sim" / "documents" / "receipts"
OUT = REPO / "notebooks" / "receipt_renders"
QUALITY = 86
# Four shots per receipt: one clean, three with the defects a hurried phone photo has.
SHOTS = {
    "rcpt_hero": [[], ["blur"], ["shadow", "perspective"], ["low_light"]],
    "rcpt_cafe": [[], ["crumpled"], ["glare"], ["rotated_8deg", "blur"]],
    "rcpt_office": [[], ["perspective"], ["shadow", "low_light"], ["crumpled", "glare"]],
}
# The print sheet's screen style has a grey page; the screenshot crop needs the paper on white.
WHITE_PAGE = "@media screen { body { background: #fff; padding: 4mm; } }"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    receipts = load("receipts", RECEIPTS / "receipts.py")
    november = load("render_november", REPO / "sim" / "documents" / "render_november.py")
    seed = json.loads((RECEIPTS / "receipts_seed.json").read_text(encoding="utf-8"))
    exe = november.browser()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for receipt in seed["receipts"]:
            shots = SHOTS.get(receipt["id"])
            if shots is None:
                continue
            computed = receipts.compute(receipt, seed["vat_rates"])
            page = receipts.page(receipt["id"], receipts.receipt_html(receipt, computed))
            html_file = work / f"{receipt['id']}.html"
            html_file.write_text(page.replace("</style>", WHITE_PAGE + "</style>", 1), encoding="utf-8")
            paper = november.screenshot(exe, work / "profile", html_file, 420, 2400)
            for number, defects in enumerate(shots, start=1):
                name = f"{receipt['id']}-{number}"
                image = november.photo(paper, defects, random.Random(zlib.crc32(name.encode())))
                target = OUT / f"{name}.jpg"
                image.save(target, "JPEG", quality=QUALITY, optimize=True)
                print(f"{name:14} {','.join(defects) or '-':22} -> {target.relative_to(REPO)} {image.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
