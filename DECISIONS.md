# Decisions log

Short entries: context, options, decision, proof, consequences. Newest at the bottom.
`R-xx` = recommendation on a fixed decision (the team decides). `D-xx` = decision on how to build (made, with proof).
All entries dated Friday 20 Nov 2026.

---

## R-01 — Recommended change to fixed decision 1: lead with the liquidity agent, not with messy data — NOT ACCEPTED

**Outcome (team, 20 Nov 2026): keep the original order. Messy data is the headline; the liquidity agent follows.** The demo script and pitch in `docs/05_DEMO_AND_PITCH.md` are written in that order. The liquidity-first order stays available as plan B if the feedback session asks for a refocus (0 h, script change only). The risk this leaves open is R2 in `docs/06_RISKS_AND_QUESTIONS.md`.

| | |
|---|---|
| Context | Fixed decision 1 makes "messy data input" the core selling point. The challenge asks for one of four agents end to end; judges score "fit to challenge / business value" first. The team was told to refocus at a previous hackathon |
| Options | (a) Keep messy data as the headline. (b) Keep building exactly the same thing, but pitch and demo it as "the liquidity agent whose forecast is right because it sees the mess" — 60% of demo time on forecast -> credit line -> approval |
| Recommendation | **(b).** No change to what is built. Change to the story, the demo order and the cut order (liquidity path is never cut) |
| Proof | (1) Challenge card: "Liquidity agent: monitors accounts, forecasts cash flow x days ahead, and automatically proposes credit facilities"; expected outcome "end-to-end use case" (file: Challenge Card). (2) Competitor research: capture, reconciliation and reimbursement are commodity; mBank already ships a 4-week forecast — the unserved part is the chain to a bank action (`docs/00_ANALYSIS.md` 5.6). (3) Spike 03: the liquidity story works on the organisers' own data. (4) Comparison below |
| Delta | Not accepted, so: demo runs messy data first (100 s), liquidity and pizzeria second (68 s). No code changes. The tax calendar + reserve task (4.6) stays should-have but is the first should-have to build, because the "VAT lost" figure ties the messy-data story to the challenge's tax agent |

| Criterion | (a) Messy data as headline | (b) Liquidity agent as headline |
|---|---|---|
| Extra effort | 0 h | 0 h |
| Fit with "pick one of four agents" | Indirect | Direct |
| "Already exists" risk | High | Medium |
| Demo value | High (live moment) | High (live moment kept, plus the bank action) |
| Works on the organisers' data | No (no documents in it) | Yes |
| Risk if the feedback session says "refocus" | Rebuild story | Already aligned |

## R-02 — Recommended reading of fixed decision 2: "real connector" for every source, third-party sandbox where one exists

| | |
|---|---|
| Context | Fixed decision 2 wants every source connected through a real running connector. No Polish bank sandbox is reachable without TPP status or certificates; GoCardless is closed; the KSeF test API needs XAdES signing |
| Options | (a) Insist on third-party sandboxes for all sources. (b) Real polling connectors for all sources; the bank that drives the demo is our own PSD2-shaped simulator; third-party sandboxes for mailbox, rates, accounting, and the sponsor's bank API (static data); KSeF API as a stretch |
| Recommendation | **(b)** |
| Proof | PKO BP sandbox requires a TPP application ([knowledge base](https://developers.pkobp.pl/en/page/knowledgeBase)); GoCardless sign-ups disabled ([page](https://bankaccountdata.gocardless.com/new-signups-disabled)); Commerzbank sandbox data is static ([help](https://service-corporates.commerzbank.com/applications-and-projects/)); KSeF auth flow ([docs](https://github.com/CIRFMF/ksef-docs/blob/main/uwierzytelnianie.md)) |
| Delta if rejected | Use the Revolut Business sandbox (can create own transactions, has webhooks) as the demo bank: +3–4 h for request signing, and a competitor's name on screen |

---

## D-01 — Plan against Sunday 10:00, not "3 days"

| | |
|---|---|
| Context | The session brief says 3 days. Transcripts and the official schedule say coding ends Sunday 10:00; it is Friday afternoon |
| Decision | All estimates use about 145 person-hours. Model deployment starts Friday evening. Feature freeze Saturday 22:00 |
| Proof | Team brainstorm notes (hand-in Sunday before 10:00; the brainstorm took place on 20 November), [official schedule](https://www.collabothon.eu/schedule/) |
| Consequence | KSeF API, OGX, FX card and free-SQL chat are stretch or cut |

## D-02 — Numbers are code; the model reads, chooses tools and writes

| | |
|---|---|
| Options | LLM computes and explains / deterministic engine computes, LLM words it |
| Decision | Deterministic finance engine. Generated text is rejected if it contains a number not present in tool results. Template fallback for every card |
| Proof | Spike 03 (forecast in 0.04 s, 1.2% error, fully traceable); challenge card asks to "explain the business logic" |
| Consequence | "Agentic" behaviour lives in tool use, scenario exploration and review decisions — stated openly in the pitch |

## D-03 — Demo bank = own PSD2-shaped simulator; Commerzbank sandbox as read-only second connector

| Option | Effort | Own data | Risk | Judge optics |
|---|---|---|---|---|
| Polish bank sandbox | not possible in time | — | — | — |
| Revolut Business sandbox | 3–4 h | yes | sign-up unverified, signing | competitor |
| Enable Banking mock | 2–3 h | yes | browser consent step | neutral |
| Open Bank Project container | 2–3 h + JVM memory | yes | config | neutral |
| **Own simulator** | 3 h | yes | none | honest "simulated bank" |
| **+ Commerzbank sandbox (read-only)** | 1.5 h box | no (static) | sign-up unverified | sponsor's API |

Decision: own simulator (must) + Commerzbank sandbox (should, time-boxed). Proof: research table in `docs/00_ANALYSIS.md` 5.1. Consequence: the bank connector is written against `contracts/bank-sim-api.md`.

## D-04 — KSeF: FA(3) XML ingestion is must-have; the test API connector is cut-first

| | |
|---|---|
| Proof | Test API needs XAdES-signed auth and encrypted async exports; no official Python client ([docs](https://github.com/CIRFMF/ksef-docs)). Estimated 4–6 h for one person who is also the only connector developer |
| Consequence | E-invoices enter as XML files (e-mail attachment or releaser). Spike 04 already parses the structure |

## D-05 — Accounting source = inFakt sandbox (not Symfonia / Merit)

| | |
|---|---|
| Proof | inFakt has a free self-registration sandbox with API-key auth ([docs](https://docs.infakt.pl/koncepcje/sandbox/)); Symfonia has no hosted sandbox found; Merit's API-on-trial is unverified |
| Consequence | "Symfonia / Merit" stay in the pitch as "same connector interface" |

## D-06 — Connectors in plain Python, not n8n

Comparison table in `docs/02_DATA_AND_SYNC.md` 3.4. n8n: +2–3 h setup, one more stateful pod, awkward idempotency. Plain code: 0 h extra, testable, same visible result on the Sources page.

## D-07 — Queue = PostgreSQL outbox (`SKIP LOCKED` + `LISTEN/NOTIFY`), not Kafka/Redis

| | |
|---|---|
| Proof | Load is a few events per second; Red Hat warns that enabling too much crashes the single node (survival guide p.1); one stateful service instead of two |
| Consequence | `contracts/events.md` defines tables and delivery rules |

## D-08 — Forecast = recurring schedules + weekday averages + known invoices + owner events. No ML model

| | |
|---|---|
| Proof | Spike 03: predicts the pizzeria low within 1.2%, 7 weeks ahead, with the owner event; misses by 20.7k without it. A statistical model would not know about a first-time closure either |
| Consequence | Chat tool `add_forecast_event` is must-have. Every forecast component is explainable |

## D-09 — No separate classifier model

| Option | Effort | Data needed | Serving | Guarantee "only predefined categories" |
|---|---|---|---|---|
| Train/host a classifier | 8+ h | labelled set (none) | second model on one GPU | yes |
| **History + keyword rules + LLM constrained to an enum** | 2 h | none | none extra | yes (JSON-schema enum) |

Decision: second row. Proof: vLLM structured outputs ([docs](https://docs.vllm.ai/en/latest/features/structured_outputs/)).

## D-10 — Agents: plain `openai` SDK + own small tool loop; tools also exposed over MCP. No heavy framework

| | |
|---|---|
| Proof | vLLM and OGX both expose the OpenAI API (RHOAI 3.5 docs); a 60-line loop has no hidden behaviour to debug at 03:00; MCP exposure keeps the OGX bonus open as a configuration change |
| Consequence | Chat = 5 fixed tools first; free SQL is a guarded extra |

## D-11 — Two demo companies: synthetic Polish company (messy) + organisers' pizzeria (clean, regression test)

Proof: spike 01 reproduces the official numbers exactly; the pizzeria gives an emergency demo that needs no document reading. Cost: one CSV loader in the bank simulator.

## D-12 — One multimodal open model served with vLLM; size chosen by GPU

| GPU | Model |
|---|---|
| 24 GB | Qwen3.5-9B FP8 (14 GB) |
| 48 GB+ | Qwen3.8-27B FP8 (30.9 GB) |
| Fallback | Mistral Small 3.1 24B quantised from `registry.redhat.io` |

Proof: model cards and Red Hat registries checked by the research agent (`docs/00_ANALYSIS.md` 5.5); memory math in `docs/01_SOLUTION.md` 6.3. Not run by us — first task on the cluster. Rejected: three models (text + classifier + vision) on one GPU.

## D-13 — Bonus set: vLLM, MLflow tracing + evaluation, Jupyter notebook; NeMo Guardrails as should-have; OGX + MCP as stretch

| Item | Hours | Cluster risk |
|---|---|---|
| vLLM | 0 | none |
| MLflow + Jupyter | 4–5 | low |
| NeMo Guardrails | 2–3 | low |
| OGX + MCP | 3–5 | medium (Technology Preview) |
| MaaS / llm-d | 4–8 each | high on one node |
| Quarkus, Dev Spaces, OpenShell | 3+ each | medium–high, no product value |

Proof: Red Hat's own advice ("focus on ~2–4", "focus on the hard criteria and the domain logic"); prerequisites read from RHOAI 3.5 docs.

## D-14 — Tax agent = calendar + reserve + "VAT lost" hint. No PIT filing helper

Proof: challenge wording ("coordinates advance tax payments and identifies optimization opportunities"); rules verified in `docs/02_DATA_AND_SYNC.md` section 5; the company has an accountant (transcript 2, 69:21).

## D-15 — FX agent = exposure list + one simulated forward. No rate prediction, no "month-boundary" warning

Proof: the brainstorm premise ("previous month's rate") is wrong — the rule is the NBP rate of the last business day before the transaction ([source](https://poradnikprzedsiebiorcy.pl/-przeliczenia-kosztu-w-walutach-obcych-kursy-walut-a-data-faktury); mechanics in spike 02).

## D-16 — Stack: Python (FastAPI) + PostgreSQL + React/TypeScript. Not Quarkus

Proof: spikes are Python; the team works in Python/TypeScript; Quarkus + LangChain4j estimated at 3–4 h even for a Java-fluent person, for one bonus item.

## D-17 — Roles rebalanced

Synthetic data, domain rules and pitch leave the frontend role; extraction joins the model owner; finance owner is also scenario owner and speaker. Reasons and hour counts in `docs/04_DEV_PLAN.md` section 2.

## D-18 — Invented vendors and tax ids only

The first version of spike 04 used real company names. Replaced with invented names and checksum-valid NIPs with prefix 999; every generated document carries SAMPLE. Reason: fixed decision 4 and avoiding documents that look like real companies' invoices.
