# Decisions log

Short entries: what was decided and what follows from it. Newest at the bottom. All entries dated Friday 20 Nov 2026.
Read this before reopening a design decision. The planning documents and spikes this log used to cite were removed; their content is in the role spec issues #1–#6, and the originals are in git history (`git show 77495ef:docs/<file>`).

---

## Product and scope

**R-01 — Headline: messy data first, liquidity agent second (team decision; the "liquidity first" recommendation was not accepted).**
The demo runs messy data first (about 100 s), liquidity and the pizzeria second (about 68 s). Liquidity-first stays as plan B if the feedback session asks for a refocus (script change only, no code). The first should-have to build is the tax calendar and reserve card, because the "VAT lost" figure ties the messy-data story to the challenge's tax agent.

**R-02 — "Real connector" for every source.**
Real polling connectors for all sources. The bank that drives the demo is our own PSD2-shaped simulator, because no Polish bank sandbox is reachable without TPP status. Third-party sandboxes only where they exist (mailbox, rates, inFakt, the sponsor's static bank API). The KSeF API is a stretch.

**D-01 — Plan against Sunday 10:00, not "3 days".**
About 145 person-hours in total. Model deployment starts Friday evening. Feature freeze Saturday 22:00. KSeF API, OGX, the FX extras and free-SQL chat are stretch or cut.

**D-14 — Tax agent = calendar + reserve + "VAT lost" hint. No PIT filing helper.**
The company has an accountant; the challenge asks to "coordinate advance tax payments and identify optimisation opportunities".

**D-15 — FX agent = FX Shield: historical-scenario downside versus the deal's profit. No rate prediction.**
Built on 756 days of real NBP rates. The average outcome is near zero, so it is useless; what matters is the bad case (worst 10% of scenarios) against the deal's margin. EUR invoices usually come out "not worth hedging"; a large USD order with a thin margin can come out "hedge". Forward and option prices are placeholders, labelled as such. A must-have for role 4 (5 h). The tax rule is the NBP rate of the last business day before the transaction, not a month-boundary effect. Spec: issue #4.

**D-11 — Two demo companies.**
A synthetic Polish company (messy data) and the organisers' pizzeria (clean data, regression test and emergency demo). Cost: one CSV loader in the bank simulator.

**D-21 — Each company has its own as-of date.**
Pizzeria Amalfi is shown on 2025-05-15 (so the forecast predicts the July low) while its full year is ingested for the year-end regression. Borsuk Labs is shown on 2026-11-21. Forecasts use only transactions booked up to the company's as-of date. A single global demo clock was rejected: the pizzeria forecast would see July's actuals.

**D-18 — Invented vendors and tax ids only.**
Invented names and checksum-valid NIPs with prefix 999; every generated document carries SAMPLE. No documents that look like real companies' invoices.

## Architecture

**D-02 — Numbers are code; the model reads, chooses tools and writes.**
A deterministic finance engine computes. Generated text is rejected if it contains a number that is not in the tool results. Every card has a template fallback. "Agentic" behaviour lives in tool use, scenario exploration and review decisions, and the pitch says so openly.

**D-03 — Demo bank = own simulator; the Commerzbank sandbox is an optional read-only second connector (time-boxed to 90 minutes).**
The bank connector is written against `contracts/bank-sim-api.md`.

**D-04 — KSeF: FA(3) XML ingestion is a must-have; the test API connector is cut first.**
The test API needs XAdES-signed auth and encrypted async exports. E-invoices enter as XML files (e-mail attachment or releaser).

**D-05 — Accounting source = inFakt sandbox (not Symfonia / Merit).**
inFakt has a free self-registration sandbox with API-key auth. Symfonia and Merit stay in the pitch as "same connector interface".

**D-06 — Connectors in plain Python, not n8n.**
n8n costs 2–3 h of setup, one more stateful pod and awkward idempotency.

**D-07 — Queue = PostgreSQL outbox (`SKIP LOCKED` + `LISTEN/NOTIFY`), not Kafka or Redis.**
A few events per second; one stateful service instead of two; the cluster is a single node. Tables and delivery rules are in `contracts/events.md`.

**D-08 — Forecast = recurring schedules + weekday averages + known invoices + owner events. No ML model.**
On the pizzeria data it predicts the low within about 1.2%, 7 weeks ahead, with the owner event, and misses by 20.7k without it. The chat tool `add_forecast_event` is a must-have. Every forecast component is explainable.

**D-09 — No separate classifier model.**
History + keyword rules + the LLM constrained to a JSON-schema enum (vLLM structured outputs). About 2 h, no extra model on the GPU.

**D-10 — Agents: plain `openai` SDK + our own small tool loop; tools also exposed over MCP. No heavy framework.**
vLLM and OGX both expose the OpenAI API, so a 60-line loop has no hidden behaviour to debug at 03:00, and MCP exposure keeps the OGX bonus open as a configuration change. Chat starts with 5 fixed tools; free SQL is a guarded extra.

**D-12 — gpt-oss-20b on the GPU, docling-serve on CPU; no vision model.**
gpt-oss-20b (open weights, vLLM 0.11 on RHAIIS, `openai` tool parser, token auth) reads Markdown, fills JSON schemas and runs the agents' tool loops. docling-serve does OCR and layout on CPU, so every document goes docling-serve → gpt-oss-20b. Both were already deployed and serving in project `cfo-ai` when recon (#7) ran, gpt-oss-20b calls tools natively in vLLM, and OCR on CPU leaves the one L4 (23 GB, 21.7 GB taken by gpt-oss-20b) to a single model. No fallback model. The earlier plan, one multimodal Qwen sized by GPU with a Mistral fallback, was dropped. Three models (text + classifier + vision) on one GPU were rejected.

**D-13 — Bonus set: vLLM, MLflow tracing + evaluation, Jupyter notebook; NeMo Guardrails as should-have; OGX + MCP as stretch.**
Not taken: MaaS, llm-d (high risk on one node), Quarkus, Dev Spaces, OpenShell (3+ h each, no product value). Red Hat's own advice is to focus on the hard criteria and the domain logic.

**D-16 — Stack: Python (FastAPI) + PostgreSQL + React/TypeScript. Not Quarkus.**
The team works in Python and TypeScript; Quarkus + LangChain4j would cost 3–4 h even for a Java-fluent person, for one bonus item.

**D-17 — Roles rebalanced.**
Synthetic data, domain rules and the pitch leave the frontend role; extraction joins the model owner; the finance owner is also the scenario owner. The pitch is a shared team task after the feature freeze.

**D-19 — The executor is called in-process by the decision endpoint, not through the queue.**
The owner must see "SIMULATED — SIM-CL-…" in the same response as the approve tap. The decision endpoint calls `execute(approval)` synchronously and still emits `execution.simulated`.

**D-20 — One writer for the ledger: the finance engine books entries from decided Matches.**
Matching (role 3) states the consequences on the Match; the finance engine (role 4) is the only code that creates Ledger entries. A Decision on a Recommendation whose subject is a Match also decides that Match, and its entries are booked already approved: one tap for the owner, never a second approval of the same purchase.
