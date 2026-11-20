# Contracts

Everything six people need to build in parallel against mocks from hour one.

| File | What it is | Who changes it |
|---|---|---|
| `schemas/*.schema.json` | JSON Schema (2020-12) for the core entities: Source, SyncRun, RawItem, Document, Account, Transaction, Counterparty, Match, LedgerEntry, Forecast, Recommendation, Approval, Event. `common.schema.json` holds Money, FxConversion, EvidenceLink, ControlLevel, ExecutionMode, PersonRef | Owner of the producing role, via PR (see below) |
| `openapi.yaml` | Backend REST API used by the frontend, the chat agent tools and the simulators (33 paths) | Role 5 (API owner) |
| `events.md` | Queue/SSE event types, payloads, idempotency keys, the live-demo chain and timing budget | Role 2 + Role 5 |
| `bank-sim-api.md` | API of the Sandbox Bank simulator (PSD2-shaped) | Role 2 |
| `fixtures/*.json` | Example payloads, one JSON array per schema. They tell one consistent story (company `co_borsuk`, the receipt Jan forwards, the 30,000 PLN credit line). Use them as mocks | Anyone, with the schema |
| `validate_fixtures.py` | Stdlib validator: `python3 contracts/validate_fixtures.py` must print `0 invalid` | - |

## Rules

1. **Fixtures are the mocks.** Frontend starts by serving `fixtures/*.json` from a static mock server; backend roles start by reading/writing the same files. Nobody waits for anybody.
2. **A contract change is a PR that touches schema + fixture together** and passes `validate_fixtures.py`. Post it in the team channel; the consumer role approves. After the feature freeze, only additive changes (new optional fields).
3. **Money is a string decimal + currency.** Never a float. Negative = money out.
4. **Every Recommendation carries `control_level`, `execution_mode`, `explanation`, `evidence` (min 1).** The UI refuses to render a card without them. This is the challenge's "analyse / recommend / approve / simulated" requirement, enforced by schema.
5. **The LLM never produces numbers that reach a schema field directly.** Numbers come from the finance engine or from extraction with a confidence value; `explanation.generated_by` says who wrote what.
6. **Ids** are opaque strings with a prefix (`doc_`, `txn_`, `mat_`, `led_`, `fc_`, `rec_`, `apr_`, `raw_`, `run_`, `src_`, `acc_`, `cp_`, `per_`, `evt_`, `ser_`, `co_`).

## Verified

- `validate_fixtures.py`: 29 examples, 0 invalid (run 2026-11-20).
- `openapi.yaml`: parses as YAML, 33 paths, every `./schemas/...` reference resolves to an existing file (run 2026-11-20).
- Not verified: no OpenAPI linter or code generator was run against the spec.
