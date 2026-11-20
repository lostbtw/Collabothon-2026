# 06 — Risks and questions

Self-contained. Owner: role 4 (questions), role 5 (risk review at each stand-up).
Likelihood and impact: H / M / L.

---

## 1. Risks

| # | Risk | L | I | Early signal | Fallback / mitigation | Owner |
|---|---|---|---|---|---|---|
| R1 | **Hard criteria not met in time** (model not serving, or app not on the cluster) | M | Fatal | No "hello model" page by Fri 22:00 | Model deploy starts in the first hour. Fallback model from Red Hat's own registry (Mistral Small 3.1 quantised). Ask Red Hat onsite at the first sign of trouble, not after two hours | 1 |
| R2 | **Judges see an expense/invoice tool, not a CFO agent** (previous-hackathon scenario: "refocus") | H | H | Feedback session reaction | Team chose messy data as the headline (R-01 not accepted), so this risk is **higher**. Mitigations: liquidity agent still shown end to end and named as what the data is for; lost-VAT counter framed as the tax agent's optimisation; their pizzeria data in the demo; plan B (liquidity-first order) ready as a 0-hour script change; ask Q8 early in the feedback session | 4 |
| R3 | **Scope too large for about 145 person-hours** | H | H | M3 missed (Sat 13:00) | Written cut order (`04_DEV_PLAN.md` section 5); feature freeze Sat 22:00; emergency pizzeria-only demo | 5 |
| R4 | GPU smaller than hoped, or unknown driver/runtime issue | M | H | `nvidia-smi` in hour 1 | Model table per GPU size; 9B model fits 24 GB; one model only | 1 |
| R5 | Cluster cannot reach the internet (Hugging Face, mailbox, NBP, inFakt) | M | H | `curl` from a pod in hour 1 | Model from `registry.redhat.io` modelcar; mailbox replaced by an in-cluster mail catcher or Telegram (HTTPS only) or the upload fallback; cached NBP table; no inFakt (XML by e-mail instead) | 1, 2 |
| R6 | Receipt photo reading is slow or wrong (never measured before the event) | M | H | First 12 photos Saturday 10:00 | JSON-schema-constrained output + checks; low confidence -> "needs review" shown as a feature; printed receipts designed to be legible (large total, clear NIP); pre-processed backup receipt | 1 |
| R7 | Live moment fails on stage (mail delay, Wi-Fi, model hiccup) | M | H | Rehearsals | Fallback ladder (`05_DEMO_AND_PITCH.md` 3.2): pre-sent receipt, Telegram, recording made at M3 | 5 |
| R8 | Single-node cluster crashes (too many components, disk pressure from model pulls, a second GPU workload) | M | Fatal | `oc adm top nodes`, disk usage | Only 3–4 platform components; limits on all pods; one model; `Recreate` strategy; no operator installs after Saturday 18:00; workbenches stopped for the demo | 1 |
| R9 | Mailbox provider blocks IMAP or throttles a fresh account | M | M | Friday evening test | Second mailbox at another provider; Telegram channel | 2 |
| R10 | Tool calling / structured output unreliable with the chosen model | M | M | First agent run Saturday | Template fallback for every card; max 6 tool calls; number check; fixed tools rather than free SQL; switch parser or model per the research table | 5, 1 |
| R11 | Tax statements challenged by a judge | M | M | — | Only verified rules are encoded; all else is a hint with "confirm with your accountant"; rule table with sources in `02_DATA_AND_SYNC.md` section 5 | 4 |
| R12 | "The bank is fake" objection | H | M | — | Said openly; PSD2-shaped API; one real third-party sandbox on the Sources page if 2.8/2.9 succeed | 4 |
| R13 | "This already exists" objection | H | M | — | Name mBank's forecast and the spend-card tools ourselves; positioning lines (`01_SOLUTION.md` section 9) | 4 |
| R14 | Integration pain: six people, late merge | M | H | Skeleton API not up by Fri 21:00 | Contracts + fixtures as mocks from hour one; skeleton API first; integration captain; three full run-throughs at Sat 22:00 | 5 |
| R15 | Demo numbers drift from the engine (fixtures say −7,870, engine says something else) | M | M | Regression test | Scenario owner = engine owner; regression test on the scenario low point; if they differ, change the script, not the engine | 4 |
| R16 | Team exhaustion; bugs at 04:00 | H | M | — | Two sleep blocks in the timeline; nothing new after Sat 22:00 | all |
| R17 | Bonus points not credited because nobody showed them to Red Hat | M | M | — | Task 1.9: show each item when it works, before Sat 20:00 | 1 |
| R18 | Synthetic documents mistaken for real ones, or real personal data used by accident | L | M | — | SAMPLE watermark and invented names/tax ids everywhere; no real mailbox, no real company documents on the cluster | 3, 4 |
| R19 | Commerzbank sandbox or inFakt sign-up takes hours | M | L | 90-minute time-box | Both are "should"; cut without changing the demo | 2 |
| R20 | Pitch length differs from the assumed 3 minutes | M | M | Ask at the feedback session | Script has a 1-minute, a 3-minute and a 5-minute variant | 4 |

Top five to watch at every stand-up: **R1, R2, R3, R6, R8**.

---

## 2. Questions for the organisers

Ask at the feedback session (Saturday 14:00–18:00) or earlier on Discord (`#Commerzbank` for business, `#Red-Hat` for technical).

### Business (Commerzbank)

| # | Question | Why we ask | Our default if no answer |
|---|---|---|---|
| Q4 | By "automatically proposes credit facilities", do you mean an overdraft / credit line on the current account, or other products too (factoring, working-capital loan)? Which Commerzbank or mBank product should the demo name? | Aim the end of the flow at the product you care about | Overdraft: mBank "kredyt w rachunku bieżącym" / Commerzbank "Gewerbekredit" |
| Q5 | May we show illustrative pricing (interest, fee) and a simulated approval, or should pricing be left out? | Avoid looking like a fake offer | Show it, labelled "illustrative, simulated" |
| Q6 | We do the liquidity agent end to end and tax + FX partially. Would you rather see more depth in liquidity (scenarios, alternatives) or a second agent? | Spend Saturday evening on what you value | Depth in liquidity |
| Q7 | Our demo company is Polish (mBank market) and we also run your German pizzeria data. Is that mix fine, or should one of them lead? | Judges' interest | Open with the pizzeria in the pitch, live moment on the Polish company |
| Q8 | Is "messy input data — several accounts, private cards, receipts, e-invoices" a problem you see with your SME clients? Does the bank see it as its business? | Validate fixed decision 1 early | Keep it as the foundation, liquidity as the headline |
| Q9 | How much autonomy would you accept for a real product: may an agent ever move money without approval (for example into the owner's own tax pocket)? | Calibrate the control model | Never without approval in this build |
| Q10 | The data sheet says the pizzeria closes for 3 weeks in June; the file shows no revenue for the whole month, and the year-end only reconciles with a 2,500 EUR opening balance that is not in the file. Intended? | Shows we read the data; confirms our numbers | Treat both as data-quality notes |

### Technical (Red Hat)

| # | Question | Why | Default |
|---|---|---|---|
| Q1 | What are the exact scoring weights (app appeal / basic challenge / bonus), and how many points per bonus item? | The scoring table in the survival guide is an image we could not read | Assume bonus is small; do 3–4 cheap items |
| Q3 | Does "run fully on OpenShift AI" allow outbound calls to external test systems (a test mailbox, the NBP rates API, an accounting sandbox)? Is outbound internet open from pods (ports 443 and 993)? | Our connectors are real | If not allowed: in-cluster mail catcher and cached rates; same connector code |
| Q11 | Which GPU does our node have, and which RHOAI components are already enabled (MLflow, TrustyAI/guardrails, OGX, MaaS)? | Model choice and bonus cost | Check ourselves in hour 1 |
| Q12 | Is pulling a 14–31 GB model from Hugging Face fine, or should we use the modelcar images? Any disk limit? | Avoid disk pressure on a single node | Use the smallest model that works |
| Q13 | For the MLflow bonus, is tracing enough or do you expect an evaluation run? For "Jupyter", does an evaluation notebook count? | Do not over-build | Both tracing and one evaluation run, from a workbench |
| Q14 | For "ogx and MCP", does an MCP server exposing our finance tools + OGX in front of the model count, or must OGX orchestrate several agents? | Decide the stretch item | Skip unless clearly cheap |
| Q15 | By when and how do we show you the bonus items? | The slide says "until XYZ" | Show each as soon as it works |

### Process

| # | Question | Default |
|---|---|---|
| Q2 | How long is the final pitch, is there Q&A, can we demo live from our laptop, and is there a second screen/phone camera? | 3 minutes + Q&A, live demo |
| Q16 | When is our feedback slot on Saturday, and who attends (business, Red Hat, both)? | Bring both the 1-minute pitch and the cluster URL |
| Q17 | What exactly must be handed in by Sunday 10:00 (challenge information card template, repo link, video)? | Card + repo tag `demo` |

---

## 3. Open items that are UNVERIFIED in the plan

| Item | Where it matters | How to close it |
|---|---|---|
| GPU type and VRAM | Model choice | `nvidia-smi` |
| Pre-enabled RHOAI components | Bonus effort | `oc get datasciencecluster -o yaml` |
| Outbound network from pods | All connectors, model download | `curl` from a pod |
| Receipt reading accuracy and latency | Live moment | 12 photos on Saturday morning |
| Docling CPU speed | PDF path | Time 5 PDFs |
| Fresh Gmail account + IMAP + app password | Mailbox connector | Create tonight |
| Commerzbank sandbox time-to-token | Should-have connector | 90-minute box |
| MLflow autolog against vLLM in RHOAI | Bonus | Try with one call |
| Qwen tool-call parser name for the chosen model (`qwen3_coder` vs `qwen3_xml`) | Agents | Check the model card on deploy; test one tool call |
| Polish quality of the chosen model | Wording in PL | Demo language is English; PL is nice-to-have |
| Reimbursement tax treatment (PL-REIMB-01), receipt-to-invoice rule (PL-RCPT-01), weekend shift of deadlines (PL-CAL-04) | Hints in the UI | Shown as hints; ask the team's accountant if reachable |
| NIP prefix 999 being unassigned | Synthetic data hygiene | Low risk; documents are marked SAMPLE |
| Pitch length | Script | Q2 |
| Scoring weights | Priorities | Q1 |
