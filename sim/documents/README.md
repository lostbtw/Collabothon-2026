# sim/documents (role 3, #16)

SAMPLE documents for the demo and for testing extraction (role 1, #17). Invented sellers, 999-prefix NIPs,
SAMPLE in the seller line, the footer and a diagonal watermark (D-18).

| What | How | Output |
|---|---|---|
| The 47 November documents of role 4's scenario (`sim/scenario/out/november_documents.json`) | `python sim/documents/render_november.py [ids]` | `november/<id>.pdf` (text PDFs) and `november/<id>.jpg` (phone photos with the scenario's defects), **committed** |
| Printable receipts for real phone photos | `python sim/documents/receipts/receipts.py` | `receipts/out/print_sheet.html` (not committed), `receipts/receipts_truth.json` |

**For role 2's releaser (#37):** `release_plan.json` artefacts like `november/nov_001.pdf` resolve against
`sim/documents/`. The hero receipt `november/doc_rcpt412.jpg` is the backup for the live phone photo.

**Rendering needs** Pillow and a headless Chrome, Chromium or Edge (set `CHROME=<path>` if it is not found).
Invoices are A4 in the document's language (pl/en); receipts use a fiscal-receipt layout. Photos are seeded per
document id: a desk, a slight tilt and noise, plus the document's `photo_defects` (rotated_8deg, blur, shadow,
crumpled, low_light, cropped_edge, perspective, glare). PDFs carry a fresh creation date on every run, so
re-rendering changes their bytes but not their content.

Correct values for every November document are in `sim/scenario/out/november_documents.json` and
`ground_truth.json` (role 4); for the printed receipts in `receipts/receipts_truth.json`.
