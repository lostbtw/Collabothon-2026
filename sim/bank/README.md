# Sandbox Bank simulator

The demo's bank and the target of every simulated execution. Contract: [contracts/bank-sim-api.md](../../contracts/bank-sim-api.md). Everything it returns is SIMULATED and invented.

## Run

```bash
cd sim/bank
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt    # Linux/macOS: .venv/bin/python
BANK_TOKEN=demo-token .venv/Scripts/python -m uvicorn bank_sim.app:app --port 8081
```

Tests: `.venv/Scripts/python -m pytest -q`. To include the test on the organisers' real file (it is not in Git):
`BANK_TEST_CSV=/path/to/pizzeria-amalfi-bank-statement-2025-v6.csv pytest -q`.

## Load the pizzeria file

```bash
curl -X POST "http://localhost:8081/admin/load-csv?profile=commerzbank_csv&accountId=acc_pizzeria" \
  -H "Authorization: Bearer demo-token" -H "Content-Type: text/csv" --data-binary @pizzeria-amalfi-bank-statement-2025-v6.csv
```

Replaces all lines of the account (safe to repeat). 1,125 lines, chronological, `entryReference` E000000001..E000001125. The 12 Swiss tranches stay booked as CHF inside the EUR account, as in the file.

## Autoload at start

The bank keeps everything in memory, so a restart empties it. To start with the pizzeria already loaded, point the bank at the CSV:

```bash
BANK_AUTOLOAD_CSV=/path/to/pizzeria-amalfi-bank-statement-2025-v6.csv uvicorn bank_sim.app:app --port 8081
```

`BANK_AUTOLOAD_ACCOUNT` picks the account (default `acc_pizzeria`). The file is loaded again after `POST /admin/reset`. If the file is missing or invalid the bank refuses to start, on purpose: an empty bank would silently ruin the demo. On the cluster the CSV goes into a ConfigMap or the image and the variable points at it (the file is not in Git).

## Accounts (invented)

`acc_pln`, `acc_eur`, `acc_owner` (private card, no balance) for Borsuk Labs, and `acc_pizzeria`. Ids and opening balances follow `contracts/fixtures/account.json`.

## No clock

The bank shows every line it holds. It had a demo clock that hid lines booked after a date; it was removed because it changed nothing on the cluster: the connector reads everything at start. To show new bank data on the demo, put a new line in with `POST /admin/transactions`; the connector fetches it on its next poll. "Today" for a company (what the forecast is computed for) is `companies.as_of_date` in the app database, not a bank setting.

## Notes for the connector (#22)

- Delta: `entryReferenceFrom` is exclusive. Pages hold 500 lines (`limit` up to 1000); follow `_links.next.href` until it is absent.
- Lines injected through `/admin/transactions` get the next reference.
- Closing balance uses a fixed CHF to EUR booking rate (`store.BOOKING_RATES`) so the pizzeria's year-end matches the organisers' sheet. The lines themselves are untouched.
- Extras beyond the contract (additive): `GET /admin/executions`, `POST /admin/reset`, `GET /health`, optional `cardLast4` on lines.
