# Spikes (throwaway code, stdlib Python 3.9, no installs)

Run from the repo root. All were run on 2026-11-20 on a laptop (macOS, Python 3.9.6).

| Spike | Command | Time | Result |
|---|---|---|---|
| 01 CSV profile + CHF fix | `python3 spikes/01_csv_chf_fix/profile_csv.py pizzeria-amalfi-bank-statement-2025-v6.csv` | 0.03 s | 1,125 rows, 1 account. Naive sum of `Amount` = 32,945.51 (wrong: mixes 12 CHF rows into EUR). Converted with the rate in the reference text = 30,766.35. Official year-end 33,266.35 => **hidden opening balance 2,500.00 EUR**. With it: 30 Jun = −20,098.69, lowest = −22,097.60 on 2025-07-03 (both match the organisers' sheet and chart) |
| 02 FX rate APIs | `python3 spikes/02_fx_rates/fx_rates.py` | 17 s total (14 s of it is the slow official ECB endpoint) | NBP table A: 200 in about 0.3 s, 404 on a Sunday, one range call returns "last business day before date" (handles the 11 Nov holiday). frankfurter.dev: 0.3 s. ECB SDMX: works but 14 s |
| 03 Forecast backtest | `python3 spikes/03_forecast_backtest/forecast_backtest.py pizzeria-amalfi-bank-statement-2025-v6.csv` | 0.04 s | Forecast made on 2025-05-15 **with** the owner-supplied event "closed 1–30 June": low point −21,824.82 on 2025-07-03 vs actual −22,097.60 on 2025-07-03 (error 272.78 EUR, 1.2%), 17 days before the first negative day, 7 weeks before the low point. **Without** the event: predicts −1,353 (misses the gap by 20,744) |
| 04 Matching engine | `python3 spikes/04_matching_engine/matching_spike.py 7` (seeds 7, 1, 2, 3, 4) | 0.1–0.2 s each | 60 synthetic purchases, 87–94 documents, FA(3)-style XML round trip. Dedup clusters 100% pure; document-to-bank matching 100% precision and recall; who-paid 97–100%; VAT-not-deductible total equals ground truth on all seeds |

Each folder has `output.txt` with the full output.

## Not run

| Planned spike | Why not | Consequence |
|---|---|---|
| Docling / OCR on a generated receipt | `files.pythonhosted.org` could not be resolved from the planning machine, so no packages could be installed | Receipt reading speed and accuracy are UNVERIFIED. First task on the cluster for role 3 |
| IMAP poll against a test mailbox | No test mailbox existed yet | UNVERIFIED. Role 2 creates the mailbox tonight and tests from a pod |

## Known limits of the spikes

- Spike 03's recurring detector does not split the tax office's three series (monthly wage tax, quarterly income tax, quarterly trade tax); it averages them. Good enough for the result above, to be fixed in the real engine.
- Spike 04's "missing document" count is inflated by its own noise lines.
- Spike 04 data is synthetic and cleaner than real life.
