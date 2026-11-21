# Ordo — Autonomous CFO

**Collabothon 2026 · Commerzbank × Red Hat · Project card**

| | |
|---|---|
| **Project name** | Ordo — Autonomous CFO |
| **One-line summary** | Ordo is a CFO for small companies: it reads their receipts, invoices and bank data on its own, forecasts cash day by day and prepares fixes that run only after the owner approves. |
| **Source code** | https://github.com/lostbtw/Collabothon-2026 |
| **Live app** | https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com (on the team's OpenShift AI cluster) |

## Technology stack

- **Languages:** Python 3.12, TypeScript, SQL
- **Backend:** FastAPI, Uvicorn, Pydantic, psycopg, uv; one package with separate processes for API, connectors, pipeline, extractor, finance engine, agents and MCP server
- **Database and messaging:** PostgreSQL 16, also used as the event queue (an outbox with `SKIP LOCKED` and `LISTEN/NOTIFY`)
- **Frontend:** React 19, TypeScript, Vite, React Router, Vitest, served by nginx
- **Platform:** Red Hat OpenShift AI on a single-node cluster with one NVIDIA L4 GPU; OpenShift builds triggered by a GitHub webhook on every push to `main`
- **Model serving:** gpt-oss-20b (open weights) on vLLM (Red Hat AI Inference Server) through KServe; docling-serve for OCR and layout on CPU
- **AI tooling:** the `openai` SDK against the in-cluster model, our own tool loop, an MCP server (`mcp` SDK), OGX in front of the model, NeMo Guardrails through the TrustyAI operator (with Presidio masking), MLflow tracing and evaluation, a Jupyter evaluation notebook
- **Observability:** OpenShift user-workload monitoring (Prometheus) with vLLM and workload alerts, Grafana dashboards for the data flow and the GPU
- **Data sources and APIs:** an IMAP invoices mailbox, the NBP (National Bank of Poland) exchange-rate API, KSeF FA(3) e-invoice XML, and our own PSD2-shaped Sandbox Bank simulator, which is also where approved actions execute
- **Hardware:** one NVIDIA L4 (23 GB) for the model; phones to photograph printed test receipts
- **Delivery:** GitHub Issues for specs and tickets, GitHub Actions CI (backend tests, contract fixtures, frontend type-check) on every pull request

## Project overview

### The problem

A small company's money is spread across a mailbox full of forwarded receipts, several bank accounts and cards, e-invoices and exchange rates. The owner usually decides by looking at the bank balance, and the balance hides a lot: money owed back to employees who paid with their own cards, taxes already owed, clients who usually pay late, and the same purchase arriving three times as XML, PDF and a phone photo. In our demo company, Borsuk Labs, the bank shows 38,400 PLN, but the real position is about −7,870 PLN two weeks later, and about −28,170 PLN if its biggest client pays late again.

The people who run these businesses are not finance professionals. Our two personas are Tomasz, 41, who runs a software studio and has no patience for finance jargon, and Vincenzo, 58, who runs a pizzeria and has little patience for software. Neither can afford a CFO, and both find out about a cash gap when a payment bounces. A cash gap a small company sees two weeks ahead can still be closed cheaply. One it sees on the day can't.

### Our solution

Ordo connects to where the money data already lives and works through it on its own: it reads every receipt and invoice, merges duplicates, matches each document to the bank line that paid it, works out who really paid, and builds one ledger the owner approves. From that ledger it forecasts cash day by day for 45 days. When a gap is coming, it explains why and prepares the fix, such as a payment reminder to a late client, a note deferring a supplier payment, or a credit line sized to the gap. A second agent, **FX Shield**, looks at foreign-currency deals and proposes a forward contract only where an exchange-rate move could really hurt the deal's profit.

What makes it different:

- **The owner stays in charge, visibly.** Every agent output carries a control level shown as a badge: *done by Ordo* (read-only, can be undone), *suggestion*, or *needs your confirmation* (prepared, runs only after a yes). In this build every approved action runs against a simulated bank, and the server refuses real execution.
- **The model never invents a number.** A deterministic finance engine computes every amount. The language model reads documents, chooses tools and writes explanations; an answer that contains a number no tool returned is rejected and replaced by a template.
- **Everything is explained.** Every forecast component, card and chat answer links to its evidence: the document, the bank line, the match, the rule.
- **Open model, own infrastructure.** The app and its model run on the team's OpenShift AI cluster with an open-weights model. Nothing is sent to a hosted LLM.

### The working prototype

What works today, on the cluster and locally:

- **Data arrives by itself.** Polling connectors read the invoices mailbox (read-only IMAP), the Sandbox Bank's accounts and the NBP exchange rates. A releaser feeds the demo scenario through these real channels over time, so nothing is uploaded by hand. A manual upload exists as a fallback.
- **Reading documents.** A photo or PDF goes through docling-serve (OCR) and then gpt-oss-20b, which fills a JSON schema. Each field carries a confidence, and uncertain fields are flagged for the owner instead of passing silently. FA(3) e-invoice XML is parsed without the model.
- **Matching and "who paid".** Duplicate copies merge into one golden record, documents are scored against noisy bank lines (including foreign invoices settled in PLN with a card spread), and Ordo decides whether the company, the owner or an employee paid. This drives reimbursements, VAT that can or can't be reclaimed, and private use.
- **The hero flow.** An employee forwards a receipt photo, Ordo reads it, sees it was paid with a private card and prepares "Pay Jan back". The owner taps once, and the payment is executed in the Sandbox Bank with a reference.
- **Cash forecast and liquidity agent.** A day-by-day forecast with a chart, a red zone and a breakdown of each component; alerts for coming gaps; a stress case; and prepared options to close the gap, cheapest first, including a credit line the owner can edit before approving.
- **FX Shield.** For each open foreign-currency invoice it compares the historical bad-case exchange-rate move (from 756 days of real NBP rates) with the company's own figures and either says "no need to hedge" or prepares a forward.
- **Taxes.** VAT, CIT advance, PIT-4 and social security come from the tax rules (from documents and salaries) and enter the forecast and a tax calendar.
- **Ask Ordo.** A chat with fixed tools over the company's data (with chat history). It can also add an owner event to the forecast, such as "closed for all of June". Questions pass NeMo Guardrails first: IBANs, card numbers and tax IDs are masked, and off-topic questions such as investment advice are refused.
- **The web app.** Overview with cash status and forecast chart; Finances (by type, by person, by client, monthly payments, all payments, each with search); To-do with sorting and a details popup; an activity log of what the owner decided and what Ordo did on its own, with undo; Settings with the owner's own cost types, people, rules, sources and alerts. A collapsible sidebar, live toasts over server-sent events, and two demo companies: Borsuk Labs (messy data, PLN) and Pizzeria Amalfi (the organisers' real-shaped data, EUR).

### Behind the build

**How the parts work together.** Each connector writes what it fetches as a raw item, then publishes an event to a PostgreSQL outbox. Separate processes pick up the events in order: the extractor reads documents; the pipeline normalises, de-duplicates and matches; the finance engine books the ledger from decided matches and recomputes the forecast; the agents turn new matches and forecasts into cards. The API serves the web app, records every decision, and calls the simulated executor in the same request, so the owner sees the result of an approval at once. Every module talks through one set of JSON-schema contracts and an OpenAPI file, with fixtures that let each part be built and tested before the others existed.

**Technical decisions that shaped it.**

- **No ML model for the forecast:** recurring schedules, weekday averages, known invoices and owner events. Every component is explainable, and on the pizzeria data it predicted the summer low within about 1.2 %, seven weeks ahead, when told about the June closure.
- **One model on one GPU:** gpt-oss-20b handles reading, classification (constrained to a JSON-schema enum) and the agents' tool loops; OCR runs on CPU. A separate vision model or classifier would not fit next to it on the L4.
- **PostgreSQL as the queue** instead of Kafka or Redis: a few events per second, one stateful service on a single node.
- **A plain tool loop on the `openai` SDK** instead of an agent framework, with the same tools exposed over MCP, so OGX could take over the loop as a configuration change.
- **Our own PSD2-shaped bank**, because no Polish bank sandbox is reachable without a licence, and approved actions need a safe place to execute.

**What we built on.** Red Hat OpenShift AI, vLLM / Red Hat AI Inference Server and KServe, the gpt-oss-20b open-weights model, docling-serve, OGX, NeMo Guardrails with Presidio via the TrustyAI operator, MLflow, Prometheus and Grafana, FastAPI, React and Vite, and the public NBP rates API. Each team member worked with Claude Code as a coding assistant. **What we created during the hackathon:** all application code (connectors, the bank simulator and releaser, the extraction and matching pipeline, the finance engine with forecast, scenarios, tax rules and FX Shield, the agents, chat and MCP server, the API and the web app), the contracts and fixtures, the synthetic demo company with its documents and printed test receipts, the evaluation notebook, and the cluster set-up, checks, alerts and dashboards.

All data in this repository is synthetic: invented companies, people, vendors and tax IDs.

### Challenges and discoveries

- **One GPU, one model.** The L4 holds gpt-oss-20b and little else, so we dropped the multimodal model and a separate classifier for OCR on CPU, with the language model reading the result. Reading takes about 11 s per document on average.
- **Reading VAT from photos is hard.** Our evaluation shows the gross amount right on every document, but VAT right on only 26 of 59. Most VAT misses come from photos. That is why every field carries a confidence and the owner confirms what goes into the books.
- **Making a language model safe with money.** We reject any generated text that contains a number no tool returned and fall back to a template, so a wrong figure can't reach the owner.
- **No bank sandbox to use.** Polish banks require a licence for their sandbox, and the KSeF test API needs signed authentication. We built our own PSD2-shaped bank and took e-invoices in as FA(3) XML files, and cut the Commerzbank sandbox and inFakt connectors when time ran short.
- **Platform quirks.** OGX passes tool results to the model in a form our vLLM chat handler did not accept, so `ordo-mcp` converts them on the way. The guardrails server ran out of memory at 1 GiB until we raised the limit. The NBP API has no tables on weekends and holidays, which the connector had to treat as normal.
- **Real-data surprises.** A single stray test event stretched a forecast to 114 days, and a fixture line duplicated a real bank line and moved the pizzeria's low. Both were found by running the full flow on the cluster, which is why the demo numbers are now pinned in CI.
- **Six people, 40 hours.** Clear contracts and fixtures from the first evening let everyone build against a running API from hour one and swap the stand-ins for the real parts as they landed.

### Results and next steps

**What we achieved.** The full flow runs on the cluster: data arrives by itself, documents are read by an open model on our own GPU, the ledger and forecast follow, and the agents prepare actions that execute only after the owner approves, in simulation.

**How we tested it.**

- 788 backend tests and 76 frontend tests, run with the contract-fixture checks in CI on every pull request. CI also pins the demo numbers: the pizzeria history, Borsuk Labs' low, the stress case and the credit line.
- An extraction evaluation of record in MLflow over 59 documents. The gross amount was right on 59 of 59, the date and seller tax ID on 58 of 59, and VAT on 26 of 59.
- A cluster smoke test (`make smoke`) that checks every component in about 40 s and reads the hero receipt end to end within 30 s.

**What we are most proud of:** an owner who isn't a finance person sees a cash gap two weeks ahead, understands why in plain words, and closes it with one approval, while every number on the screen comes from deterministic code.

**Current limitations:**

- VAT reading on photos is weak.
- Forward and option prices in FX Shield are labelled placeholders.
- Undo of an approved action is not yet supported by the backend.
- Own cost types are kept in the browser.
- The Sandbox Bank keeps its state in memory.
- There is no fallback model.
- Every action is simulated by design.

**What we would improve next:**

- Better VAT reading (for example by checking VAT against the gross amount and the rate).
- Real bank connectivity through a licensed partner, with Commerzbank as the obvious candidate.
- The KSeF API connector and an accounting-tool connector.
- Undo for approved actions.
- Turning the simulated executor into "permitted" execution with per-action limits the owner sets.

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
