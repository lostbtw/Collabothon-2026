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

## Accounts (invented)

`acc_pln`, `acc_eur`, `acc_owner` (private card, no balance) for Borsuk Labs, and `acc_pizzeria`. Ids and opening balances follow `contracts/fixtures/account.json`.

## As-of date (the "demo clock")

`POST /admin/clock {"now": "2025-05-15", "accountId": "acc_pizzeria"}` hides every line booked after that date, for that company only. Without `accountId` it sets one global date for all accounts. `{"advanceDays": 10}` moves it forward. A later date reveals the hidden lines, which always have higher entry references, so a delta cursor never misses them.

## Notes for the connector (#22)

- Delta: `entryReferenceFrom` is exclusive. Pages hold 500 lines (`limit` up to 1000); follow `_links.next.href` until it is absent.
- Lines injected through `/admin/transactions` get the next reference. Inject with a booking date on or before the as-of date, or the line stays hidden.
- Closing balance uses a fixed CHF to EUR booking rate (`store.BOOKING_RATES`) so the pizzeria's year-end matches the organisers' sheet. The lines themselves are untouched.
- Extras beyond the contract (additive): `GET /admin/clock`, `GET /admin/executions`, `POST /admin/reset`, `GET /health`, optional `accountId` and `advanceDays` on the clock, optional `cardLast4` on lines.
