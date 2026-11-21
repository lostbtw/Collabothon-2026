# Ordo — Autonomous CFO

Collabothon 2026 · Commerzbank × Red Hat

## Project name

Ordo — Autonomous CFO

## One-line summary

Ordo is a CFO for small companies: it reads their receipts, invoices and bank data on its own, forecasts cash day by day and prepares fixes that run only after the owner approves.

## Technology stack

- **Code:** Python 3.12 (FastAPI, Pydantic, psycopg), TypeScript (React 19, Vite), SQL
- **Data:** PostgreSQL 16, also used as the event queue
- **Platform:** Red Hat OpenShift AI, single node, one NVIDIA L4 GPU
- **AI:** gpt-oss-20b (open weights) on vLLM / KServe, docling-serve OCR, MCP, OGX, NeMo Guardrails, MLflow
- **Ops:** Prometheus, Grafana, GitHub Actions
- **Data sources:** IMAP mailbox, NBP exchange-rate API, KSeF FA(3) e-invoices, our own PSD2-style test bank

## Project overview

### The problem

Small business owners decide by looking at the bank balance, and the balance lies. It doesn't show money owed back to employees, taxes already due, or clients who always pay late. In our demo company the bank shows 38,400 PLN, but two weeks later the company is 7,870 PLN short. Owners like this can't afford a CFO and find out about the gap when a payment bounces.

### Your solution

Ordo connects to the mailbox, the bank accounts and the exchange rates, and keeps the books itself. It forecasts cash 45 days ahead. When a gap is coming, it explains why and prepares the fix: a payment reminder, a deferred payment or a credit line. A second agent, FX Shield, proposes a currency hedge only when an exchange-rate move could really hurt a deal.

What makes it different:
- The owner decides every action. Nothing runs without a yes, and every action runs in a simulated bank.
- All numbers come from code. The AI reads and explains but never invents a figure.
- The open-weights model runs on our own cluster. No data goes to an outside AI service.

### The working prototype

All of this works on the cluster today:

- **Automatic intake.** Data arrives on its own from the mailbox, the bank and the NBP rates.
- **Document reading.** A receipt photo or PDF is read into fields, and unsure fields are flagged.
- **Matching.** Duplicate copies merge, each document is matched to its bank line, and Ordo works out who paid: the company, the owner or an employee.
- **One-tap approval.** Example: an employee's private-card receipt becomes "Pay Jan back", and one tap pays it in the test bank.
- **Forecast.** A cash chart with the coming gap, its causes, a stress case and options to close it.
- **FX Shield.** Decides "hedge" or "no need" per foreign-currency invoice, using 756 days of real NBP rates.
- **Ask Ordo.** A chat over the company's data. Bank account and card numbers are masked, and off-topic questions are refused.
- **Web app.** Overview, Finances, To-do, an activity log with undo, Settings, and two demo companies: a software studio and a pizzeria.

### Behind the build

Connectors write raw data. A PostgreSQL event queue passes it to the extractor, then the matching pipeline, then the finance engine, then the agents. The API records every decision and runs the approved action in the test bank in the same request.

Key decisions:
- **A forecast without ML:** recurring payments, averages and known invoices. It is fully explainable and was within about 1.2% on the pizzeria data, seven weeks ahead.
- **One model on one GPU:** gpt-oss-20b does reading, sorting and the agents' tool calls; OCR runs on CPU.
- **Our own test bank:** Polish banks need a licence for sandbox access.

Built on OpenShift AI, vLLM, gpt-oss-20b, docling-serve, OGX, NeMo Guardrails, MLflow, FastAPI and React. The team wrote all application code, the demo data and the cluster setup during the hackathon, working with Claude Code as a coding assistant.

### Challenges and discoveries

- **One GPU holds one model.** We dropped a vision model and do OCR on CPU, at about 11 seconds per document.
- **VAT on photos is hard to read.** Only 26 of 59 were right, so each field shows how sure Ordo is and the owner confirms.
- **Keeping the AI honest.** An answer with a number that no calculation produced is rejected and replaced by a template.
- **Running the full flow on the cluster** found two bad test records that broke the forecast. The demo numbers are now pinned in CI.

### Results and next steps

The full flow runs on the cluster: data in, books, forecast, an agent's proposal, approval and simulated execution.

**Tested with:**
- 788 backend and 76 frontend tests in CI.
- An MLflow evaluation on 59 documents: total amount right on 59, date and seller tax number on 58, VAT on 26.
- A 40-second cluster smoke test.

**Proudest of:** an owner who isn't a finance person sees a cash gap two weeks early and closes it with one tap.

**Limitations:**
- VAT reading on photos.
- Every action is simulated.
- There is no fallback model.

**Next:**
- Better VAT reading.
- A real bank connection through a licensed partner such as Commerzbank.
- A KSeF API connector.

## Source code repository

https://github.com/lostbtw/Collabothon-2026

---

## For developers

| Where | What |
|---|---|
| [Issues #1–#6](https://github.com/lostbtw/Collabothon-2026/issues?q=label%3Aspec) | One spec per role; each role's tickets are its sub-issues |
| [CLAUDE.md](CLAUDE.md) | Roles, folders, the work loop, hard rules, milestones, cut order |
| [GLOSSARY.md](GLOSSARY.md) | The project's vocabulary |
| [contracts/](contracts/README.md) | Schemas, API, events and fixtures every role builds against |
| [DECISIONS.md](DECISIONS.md) | Why things are the way they are |
| [deploy/README.md](deploy/README.md) | The cluster: what runs where, set-up, checks, OGX, guardrails, monitoring |

Set-up per person: clone, `echo <your role number 1-6> > .role`, start Claude Code in the folder, pick a ticket in the browser (see `CLAUDE.md` section 2) and tell Claude its number. One branch and one pull request per ticket; nobody commits to `main` directly.

API with demo data, one command (no Docker needed): `uv sync --group localdb && uv run python -m backend.api.dev`, then http://localhost:8080/api/v1/inbox (docs at http://localhost:8080/docs). Every path of `contracts/openapi.yaml` answers from the database, loaded with `contracts/fixtures`; SSE at `/api/v1/events/stream` replays `fixtures/event.json` and then relays new events.

Frontend: `cd frontend && npm install && npm run dev` (http://localhost:5173, sample data). Against the local API: `VITE_API_MODE=live VITE_API_PROXY=http://localhost:8080 npm run dev`. Details in [frontend/README.md](frontend/README.md).

Backend: one Python 3.12 package in `backend/`, managed with [uv](https://docs.astral.sh/uv/). `uv sync` installs it; each process starts as `uv run python -m backend <api|connectors|pipeline|agents>`. Your process goes in `backend/<your folder>/main.py` as `run(argv)`; until then the entrypoint is a placeholder. Tests live next to the code they test (`backend/<folder>/tests/`).

Database: Postgres, schema in `backend/db/migrations/`; `uv run python -m backend.db setup` migrates and seeds the database at `ORDO_DATABASE_URL`. Entities are read and written through `backend.db.store.Store`; pydantic models of every contract entity are in `backend.db.contracts.MODELS`. Tests that need a database use the `db` fixture: CI provides Postgres, and locally `uv sync --group localdb` installs a private Postgres (pgserver) so no Docker is needed; without either, those tests are skipped.

Checks (the same ones CI runs on every pull request): `python3 contracts/validate_fixtures.py` (expects `0 invalid`), `uv run python -m pytest` (all backend tests), and `npx tsc --noEmit` in `frontend/`.

Everything in this repository is synthetic. Company, people, vendors and tax ids are invented and marked SAMPLE.
