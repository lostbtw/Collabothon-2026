# #55 M4: run the liquidity flow on the cluster

Hand-off for the agent that finishes ticket #55 (R5·M4 Liquidity flow on real data, pizzeria June event included). The code is on `main` (`backend/api/demo.py`); what is left are the acceptance runs.

The cluster is shared by six people and holds the demo. Every step that writes to it (SQL, `POST`, the demo script) runs only after the human says yes to that step. Reads (`GET`) are free.

## Done on 2026-11-21 (verified)

1. Removed two stray test records that broke the flow:
   - `co_borsuk` forecast event `FX Shield test trigger` (2027-03-01). It stretched the horizon to 114 days and put a −34,298.71 PLN low in February, so the chart stayed below zero after the credit line.
   - `co_amalfi` transaction `txn_pz0615` from `contracts/fixtures`, a duplicate of a real CSV line. It moved the June low to −17,585 instead of about −21.8k.
2. Recomputed both forecasts:
   - `co_borsuk`: 45 days, `cash_gap` 2026-11-30..12-06, low −8,474.71 PLN.
   - `co_amalfi`: low −746.89 EUR on 2025-06-01; with the June closure, −21,960.44 on 2025-07-03 (checked on a copy of the cluster data).
3. Superseded the stale credit-line card. The liquidity agent keeps an open card when the alert's start date and shortfall are unchanged, even if the forecast behind it changed. Fixed `ordo-agents` (it crashed on start: missing `tracing` import), after which it created `rec_cl_fc_co_borsuk_dc10a7c36d`: "Open a 30,000 PLN credit line before 30 November", with reasons from November and December.

`setup.sh db-fixtures` loads `contracts/fixtures` on top of the real data; that is how `txn_pz0615` arrived. Reset the demo between runs some other way, or the line comes back.

## Open issues

- No `finance` process runs on the cluster: its queue holds thousands of pending events. Forecasts still recompute when the API approves a card, but ledger entries from confirmed matches are not booked. Owner: roles 1 and 4.
- Liquidity agent: a forecast change with the same alert start and shortfall keeps the old card (`backend/agents/liquidity.py`, `on_forecast_updated`, the `signature` check). Owner: role 5.

## Steps

### 1. Check before the run

`GET /api/v1/inbox?company_id=co_borsuk` on `https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com`. Done when exactly one `credit_line` card has status `new`, offers 30,000 PLN, and `GET /forecast/latest?company_id=co_amalfi` lists no events. Anything else goes to the human.

### 2. Run the flow

```bash
uv run python -m backend.api.demo liquidity --api https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com/api/v1
```

It approves the card edited to 25,000 and adds the June event to the pizzeria, so it runs once per demo state. Done when it prints `PASS` with every step `OK`; paste the report into the ticket.

### 3. Close the ticket

Done when the human has run the whole 3-minute demo three times in the 22:00 slot, resetting the data between runs, and #55 is closed with the step-2 report.
