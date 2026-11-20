# sim/scenario — Borsuk Labs demo data (role 4, #15)

All data is synthetic and marked SAMPLE. NIPs start with 999. IBANs use check digits `00`, so they are not valid accounts.

## Files

| Script | Writes |
|---|---|
| `world.py` | — shared company, accounts, People, demo-day rates (4.41 PLN/EUR, 4.0613 PLN/USD) |
| `bank_2026.py` | `out/bank_acc_pln.csv`, `out/bank_acc_eur.csv`, `out/bank_acc_owner.csv` |
| `story_2026.py` | `out/people.json`, `out/story_items.json`, then runs the story check |
| `fa3_2026.py` | `out/fa3/<YYYY-MM>/<id>.xml` (KSeF FA(3) invoices), `out/fa3_index.json` |
| `november_2026.py` | `out/november_documents.json` (values of the November PDFs and photos) |
| `release_2026.py` | `out/ground_truth.json`, `out/release_plan.json` |

Run all, in this order:

```
for s in bank story fa3 november release; do python3 sim/scenario/${s}_2026.py; done
```

Each run gives byte-identical output. After a change to a script, run all five and commit the script and `out/` together.

Tests: `python3 -m unittest discover -s sim/scenario/tests -v` (or `python -m pytest sim/scenario`). They generate everything twice into a temporary folder and check: byte-identical output, committed `out/` is current, the story table, People rules, SAMPLE names and 999 NIPs, the release plan (nothing before November goes through extraction) and the ground-truth links. Set `FA3_XSD=<folder>` to also validate the FA(3) files.

## November documents (`out/november_documents.json`)

47 documents dated 1–20 Nov 2026 (41 originals and 6 duplicates): the values role 3 renders as PDF or photo (#16). Each entry has seller, buyer, number, dates, lines, totals (decimal strings), payment, who paid, the bank line (Sandbox Bank entry reference) and the target file `november/<id>.pdf|jpg`.

- 10 receipts paid with private cards (reimbursements owed on 30 Nov, 5,169.00 PLN), ids `doc_rcpt401`–`doc_rcpt412`. The hero receipt `doc_rcpt412` (1,299 PLN, no company NIP) has the same values as `contracts/fixtures/document.json` and `live_in_demo: true`.
- Company-card purchases: photographed receipts (fuel, food, taxi) or e-mailed PDF invoices (online shops, coworking, accounting office). About half of the small daily purchases have no document (M7).
- Foreign SaaS invoices in USD/EUR, reverse charge (M6); the Lingua Bridge invoice (EUR).
- Owner's card (M3): train, hotel, taxi, Figment.
- Lakeshore Robotics sales invoice `2026/11/045`, 40,000 USD, due 5 Jan 2027 (FX Shield).
- Duplicates (M5): ElektroMarkt laptop and Biurosfera also arrive as FA(3) XML (`out/fa3/2026-11/`); Paliwex, hotel, coworking and CodeHarbor arrive twice.
- Photo defects (M12) for 8 photos: `rotated_8deg`, `blur`, `shadow`, `crumpled`, `low_light`, `cropped_edge`, `perspective`, `glare`.
- `doc_type` and `flags` use the contract values (`invoice`, `simplified_invoice`, `receipt`; `vat_not_deductible`, `buyer_not_company`, ...).

## Ground truth (`out/ground_truth.json`)

- `documents`: all 546 documents (FA(3) and November) with `paid_by` (`company_account`, `owner_private`, `employee_private`, as in the Match contract), `match_type`, the bank line (`account` + `entry_reference`), `duplicate_of`, `vat_deductible`, `vat_lost` and the messiness tags.
- `duplicates`: 6 clusters (original + copies).
- `bank_lines_without_document`: every other bank line with a reason: `bank_fee` (M7), `tax_or_social_security`, `salary`, `reimbursement_payout`, `internal_transfer`, `private_purchase_on_company_account` (M4), `foreign_invoice_not_in_backfill`, `document_missing` (M7), `private`.

Entry references (`E000000001`, ...) are the ones the Sandbox Bank (`sim/bank`) gives when it loads the account's CSV: booking order, and within a day the reverse of the file order.

## Release plan (`out/release_plan.json`)

What role 2's releaser (#37) sends: 1,616 items, each with `mode`, `scenario_date`, `channel`, `artefact`, the bank line or document id, `sender` and `via_model`.

- `backfill` (before the demo, in date order): 1,070 bank lines, 499 FA(3) invoices (purchases by e-mail, sales by the accounting API with e-mail as fallback), 31 November documents.
- `drip` (during the demo, 20–40 s apart, `offset_seconds`): 15 items, the foreign SaaS invoices and the duplicates.
- `live`: the hero receipt, photographed with a real phone; the rendered photo is the backup.
- `via_model` is true only for November PDFs and photos. FA(3) XML, bank lines and the accounting API need no model.
- Senders: `faktury@dostawcy.sample` (supplier invoices), `owner@borsuk-labs.sample` and each team member's own address (8 in total).

## FA(3) invoices (`out/fa3/`)

499 KSeF FA(3) invoices: 497 issued 1 Dec 2025 – 31 Oct 2026 (458 purchases, 39 sales) and 2 November duplicates (M5). They follow the official schema `http://crd.gov.pl/wzor/2025/06/25/13775/` (FA (3), schema 1-0E). `bank_2026.py` attaches the invoice data to the bank lines, so every amount and date agrees with the bank CSVs.

- Purchases (Borsuk Labs is the buyer): coworking, accounting office, 4 B2B contractors, card purchases at Polish merchants, irregular purchases. Card invoices are marked paid (`Zaplacono`, `FormaPlatnosci` 2); transfer invoices carry the due date and the seller's account.
- Sales (Borsuk Labs is the seller): Meblostyl, Piekarnia Złoty Kłos, Kadrownia (23% VAT, PLN) and Nordwind (EUR, `np II`, reverse charge). Invoices are issued on the last day of the month; December 2025 invoices are the ones paid in January.
- Without a bank line (8): the open October invoices Meblostyl `2026/10/042` (36,900 PLN) and Nordwind `2026/10/044` (18,400 EUR), and 6 cash purchases (M8). The Warsaw trip in May is paid with the owner's card (M3).
- Not FA(3): foreign vendors (SaaS, Lingua Bridge, EUR card purchases), private receipts, salaries, ZUS and taxes. KSeF holds only invoices of Polish sellers.
- `fa3_index.json` lists every invoice with its amounts (decimal strings), file and the bank line it belongs to (`null` if none).
- Seller NIPs are invented, start with 999 and have valid check digits. ElektroMarkt keeps `9990000043` from the contract fixtures.

Validate against the schema: download `schemat.xsd` and its imports from crd.gov.pl into a folder, then run `python3 sim/scenario/fa3_2026.py --xsd <folder>`. It needs `xmllint` and stops if a file fails.

## People (`out/people.json`)

Same fields as `backend/db/seed_data/people.json` (role 5): `id`, `company_id`, `name`, `email`, `role`. It keeps role 5's ids (`per_tomek`, `per_jan`, `per_amalfi_owner`) and adds the rest of the Borsuk Labs team: 1 owner, 2 employees (Jan Kowalski, Marta Zielinska), 4 B2B contractors. All e-mail addresses end in `.sample`. The pay run in the bank lines uses the same people.

## Story items (`out/story_items.json`)

The known future cash items of the liquidity story, as of 21 Nov 2026: VAT, Meblostyl, the pay run (7 items = 58,000), 10 reimbursement receipts (= 5,169, the live receipt `doc_rcpt412` 1,299 included), 1–5 Dec costs (= 5,701), Nordwind 18,400 EUR (expected 7 Dec, stress 21 Dec), ZUS, PIT-4 and CIT-5 in December, and the Lakeshore order (40,000 USD = 162,452 PLN, due 5 Jan 2027). Each item has `amount` (decimal string + currency) and `amount_pln` at the demo-day rate.

Only items that the story table uses are listed. It is not a full forecast: the forecast engine (#28) adds recurring items, such as the accounting office on 10 Dec.

### Story check

`story_2026.py` starts from the bank closing balances (24,730.15 PLN + 3,100 EUR × 4.41) and applies the items day by day (money out first within a day). It stops with an error if a value differs from the story table by more than 50 PLN, if the lowest point is not on 5 Dec, or if the People rules fail.

| Date | Story | Exact | Difference |
|---|---|---|---|
| 21 Nov | 38,400 | 38,401.15 | +1.15 |
| 25 Nov | 24,100 | 24,101.15 | +1.15 |
| 27 Nov | 61,000 | 61,001.15 | +1.15 |
| 30 Nov | −2,169 | −2,167.85 | +1.15 |
| 5 Dec (lowest) | −7,870 | −7,868.85 | +1.15 |
| 7 Dec | 73,230 | 73,275.15 | +45.15 |
| Stress (Nordwind 21 Dec) | −28,170 | −28,168.85 | +1.15 |
| Before the live receipt | −6,571 | −6,569.85 | +1.15 |

The differences come from the story's rounding: 3,100 EUR × 4.41 = 13,671 (story: 13,670), 18,400 EUR × 4.41 = 81,144 (story: 81,100). The spec says: if they differ, change the script, not the engine.

## Bank lines, 1 Jan – 20 Nov 2026

`bank_2026.py` writes `out/bank_<account>.csv`, about 1,070 rows in total (the pizzeria file has 1,125). Routine rows come from a generator with a fixed seed (2026); the November story rows are hand-written. The output is byte-identical on every run.

| File | Account | Currency | Rows | Opening 1 Jan | Lowest | Closing 20 Nov |
|---|---|---|---|---|---|---|
| `bank_acc_pln.csv` | company, card *4417 | PLN | 719 | 82,730.06 | 3,498.73 (6 Oct) | 24,730.15 |
| `bank_acc_eur.csv` | company, card *2290 | EUR | 94 | 7,909.43 | 3,100.00 | 3,100.00 |
| `bank_acc_owner.csv` | owner's private card *9021, never company cash | PLN | 257 | 12,000.00 | — | — |

The closing balances are fixed by the story: 24,730 PLN + 3,100 EUR × 4.41 ≈ 38,400 PLN on 21 Nov. The opening balances are computed backwards and are not in the CSV (same as the pizzeria file). The script stops if a company balance goes below zero.

### Format (same as the organisers' pizzeria CSV)

- UTF-8 without BOM, delimiter `;`, every field quoted, LF line ends.
- Rows are newest first (20 Nov at the top).
- Dates `dd.mm.yy`. Amounts with decimal comma and no thousands separator (`-1299,00`). Negative means money out.
- Columns: `Account Number`, `Booking Date`, `Value Date`, `Transaction Type`, `Payment Reference`, `Beneficiary/Payer`, `Counterparty Account`, `Bank Code`, `Amount`, `Currency`, `Info`.
- `Bank Code` is an invented BIC (`SMPLPLPWXXX`, `SMPLDEFFXXX`); empty for card lines, as in the pizzeria file.
- Transaction types from the pizzeria file: `RENT PAYMENT`, `SUPPLIER PAYMENT`, `SALARY PAYMENT`, `GIRO CARD PAYMENT`, `DIRECT DEBIT`, `INTERNATIONAL WIRE TRANSFER`, `TAX OFFICE TRANSFER`. Added for Borsuk Labs (no pizzeria equivalent): `INCOMING TRANSFER`, `OUTGOING TRANSFER`, `INTERNAL TRANSFER`, `BANK FEE`.
- Card lines: value date = purchase date, booking date = next bank day. Foreign-currency card lines carry the original amount in `Payment Reference` (`... 45.00 USD KARTA *4417`).
- Only weekdays that are not Polish public holidays are booking days.

### What the data contains

- Monthly, on the date or the next bank day: coworking 2,460 (1st), accounting office 1,230 (10th), ZUS about 9,400 (15th), PIT-4 about 3,850 and CIT-5 advance about 7,050 (20th, separate series), VAT 12–16k (25th), bank fees.
- Pay run on the last bank day, 58,000.00: 2 employees and the owner's board fee (`SALARY PAYMENT`), 4 B2B contractors (`SUPPLIER PAYMENT`), plus 1–4 reimbursements (`OUTGOING TRANSFER`, M1/M2). The board fee also appears as income on the owner's account.
- SaaS: 6 USD vendors = 1,150 USD and 2 EUR vendors = 180 EUR on card *4417, at card rates with a 0.5–4.5% spread (M6). `PIXELBOARD` on 20 Nov equals fixture `txn_731`.
- Clients: Meblostyl (on time, 27th), Piekarnia Złoty Kłos and Kadrownia (PLN, a few days late). Sales fall through the year (×1.18 in January to ×0.77 in October), so the cash gap builds up.
- Nordwind: 5 EUR invoices (due on the 14th of odd months), paid 21–25 days late (average exactly 23). The next bank day most of the money is converted to PLN (`INTERNAL TRANSFER` on both accounts).
- One irregular purchase of 3–9k per month (hardware, conference, chairs, legal).
- About 40 daily card purchases per month on *4417, about 6 on the EUR card *2290, about 20 private ones on the owner's card.
- Messiness: M3 (Figment design tool monthly and a Warsaw trip in May on the owner's card, plus 4 rows in November), M4 (4 private purchases on the company card), M6, M7 (bank fees without document), M9 (noisy descriptors with order numbers).
- Not in the bank: the 1,299 PLN live receipt (Jan paid with his private card); everything after 20 Nov (VAT 25 Nov, Meblostyl 27 Nov, pay run 30 Nov, Nordwind 7 Dec).
- Rows without the word SAMPLE: bank fees and payments to public institutions (ZUS, tax office), as in the pizzeria file.
