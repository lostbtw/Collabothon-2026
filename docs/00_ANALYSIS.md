# 00 — Analysis and feasibility

Self-contained. Written Friday 20 Nov 2026, 15:00–17:00 CET.
Claim labels: `VERIFIED (source)` = checked today against a file, a spike or a web source. `UNVERIFIED (reason)` = assumption.
Web research was done by research sub-agents with web access; some official pages blocked automated fetching, which is noted per claim.

---

## 0. Ten findings that change the plan

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| 1 | **There are about 43 hours left, not 3 days.** The first transcript says hand-in is "Sunday before 10:00"; the second says "today is 20 November" and "feedback session tomorrow". Today is Friday 20 Nov, 15:11 | VERIFIED (both transcripts; system clock; official schedule: coding ends Sun 10:00, presentations 10:30–15:00 — [collabothon.eu/schedule](https://www.collabothon.eu/schedule/)). Pitch length: UNVERIFIED | About 100 person-hours of real building. The brainstorm plan "plan today, start tomorrow evening" would fail the hard criteria. Deploy a model **today** |
| 2 | The feedback session is tomorrow and the team was told to refocus at a previous hackathon | VERIFIED (transcript 2, 46:53 and 66:00) | Feedback sessions are Saturday 14:00–18:00 (VERIFIED, official schedule). A 1-minute pitch and a clickable mock must exist by Saturday 13:00 (see `05_DEMO_AND_PITCH.md`) |
| 3 | Scoring: no app or no basic challenge = zero points. Red Hat says "focus on the hard criteria and the domain logic"; bonus weight was reduced | VERIFIED (Red Hat slides p.13; survival guide p.2) | 2–3 cheap bonus items, not more |
| 4 | The challenge card asks for four explicit distinctions (analyse / recommend / approve / simulated) and "explain the business logic" | VERIFIED (challenge card p.1–2) | These become mandatory fields on every recommendation (`contracts/schemas/recommendation.schema.json`) |
| 5 | The pizzeria file has **two** traps, not one: CHF rows in a EUR account **and** a hidden opening balance of 2,500 EUR | VERIFIED (spike 01) | Free, impressive data-quality demo on the organisers' own data |
| 6 | A simple, explainable forecast predicts the pizzeria's low point within 1.2%, seven weeks ahead — **but only if the owner tells it about the June closure** | VERIFIED (spike 03) | No neural forecasting. The chat's most valuable job is collecting future events from the owner |
| 7 | Rule-based matching reaches 97–100% on synthetic messy data | VERIFIED (spike 04; synthetic, easier than reality) | Matching is code, not LLM. LLM is for reading documents and wording |
| 8 | Real bank sandboxes in Poland need TPP status or certificates; GoCardless is closed to new sign-ups | VERIFIED (PKO BP knowledge base; GoCardless page) | The demo bank is our own PSD2-shaped simulator; a third-party sandbox is a time-boxed extra |
| 9 | The KSeF test API is open (self-signed certificate) but needs XAdES signing and encrypted exports, with no official Python client | VERIFIED (CIRFMF docs) | KSeF API is a stretch goal; FA(3) XML files are always supported |
| 10 | Several brainstorm tax statements are wrong or incomplete (FX rate rule; "the company can do nothing with an invoice in the employee's name"; "VAT is returned by ZUS at year end") | VERIFIED (section 4.3) | Encode only verified rules; everything else is a hint with "confirm with your accountant" |

No fixed decision is infeasible. All five have a workable form (section 4.1), so the session continued past the checkpoint.

---

## 1. Challenge breakdown

### 1.1 Requirements

| Requirement | Source | Type |
|---|---|---|
| App runs on the team's OpenShift AI cluster | Survival guide p.1; challenge card p.3 ("needs to run fully on OpenShift AI") | **Hard** |
| App uses an open-source / open-weights LLM deployed on that cluster | Survival guide p.1; challenge card p.3 | **Hard** |
| "Agentic application" | Challenge card p.3 | Expected |
| At least one of four use cases as a complete workflow: data input -> explainable recommendation -> user interaction | Challenge card p.1 | **Business must** |
| Show: what agents analyse independently / recommend / what needs approval / simulated or permitted | Challenge card p.1 ("if possible") | Strongly expected |
| Explain the business logic; show how the owner understands and responds | Challenge card p.2 | Expected |
| "Innovations for all generations": understandable for owners with different technical confidence; "fun and easy to use" | Challenge card p.2, p.4 | Theme fit |
| Git repo shared before credentials are issued; organisers read the code early | Challenge card p.3; Red Hat slides p.12 | Process |
| Environment is deleted after the event | Challenge card p.3 | Constraint |
| Sample data is optional; "numbers created with AI, not necessarily realistic" | Sample data sheet | Freedom to use own data |

### 1.2 Scoring

| Part | What is known | Source |
|---|---|---|
| Split | "application appeal in general, basic challenge and bonus points" | Red Hat slides p.13 |
| Zero rules | No application = no points; no basic challenge = no points | same |
| Basic challenge | Deploy on OpenShift; use a model deployed on RHOAI; use case implementation; UI/UX | Red Hat slides p.9 |
| Bonus | 11 items; "focus on ~2–4"; weight reduced versus last year; show them to Georg and Karsten to get the points | Red Hat slides p.13; survival guide p.2 |
| Exact weights | A scoring table image exists in the survival guide but did not survive text extraction | UNVERIFIED — ask (Q1 in `06_RISKS_AND_QUESTIONS.md`) |
| Event-level criteria | "fit to challenge/business value, technical implementation/level of complexity, innovation, and design". Every team with a working prototype pitches | VERIFIED ([collabothon.eu/rules](https://www.collabothon.eu/rules/)) |
| Awards | The Red Hat challenge competes for the Technology Award; there is also an Audience Award | VERIFIED (same page) |
| Repo rule | Fresh GitHub repo created no earlier than Friday; no pre-existing proprietary code | VERIFIED (same page) |
| Challenge brief on the website | Asks: which decisions to automate, how agents collaborate, combining customer data + market information + banking products, trust/transparency/regulation, the right level of autonomy | VERIFIED ([collabothon.eu/challenges](https://www.collabothon.eu/challenges/)) |

### 1.3 Constraints

| Constraint | Value | Source |
|---|---|---|
| Cluster | Single node, 32 CPU, 128 GB RAM, "GPU-backed" | Red Hat slides p.11 |
| GPU model and VRAM | Not stated | UNVERIFIED — check in hour 1 (`nvidia-smi` / node labels) |
| Stability | "If you enable all features … you'll probably crash your single node cluster" | Survival guide p.1 |
| Platform version | RHOAI self-managed 3.5 | Survival guide links |
| Support | Red Hat onsite (Georg, Karsten) + remote via Discord | Red Hat slides p.11 |
| Coding assistants | Proprietary ones allowed for building; OSS agents on the cluster preferred for the bonus | Challenge card p.4 |

### 1.4 What "winning" probably looks like

Two juries, two different eyes (UNVERIFIED — inferred from the materials, not stated):

| Judge | Cares about | What convinces them |
|---|---|---|
| Commerzbank business (challenge authors) | One of **their** four agents, working end to end; a bank product at the end of the flow (credit facility); owner stays in control; understandable by a non-expert | A cash gap found early, a credit line proposed with reasons and alternatives, an approval click, a clearly labelled simulated execution. Their own pizzeria data handled correctly |
| Red Hat technical | Really running on the cluster; model served on RHOAI; sensible, stable use of 2–4 platform features; code in the repo from early on | A live route URL on the cluster, a served model in the RHOAI dashboard, traces in MLflow, no crash |

The biggest strategic risk: the product is seen as "invoice scanner / expense tool" (crowded market) instead of "CFO agent". I recommended leading the pitch with the liquidity agent (`DECISIONS.md` R-01); the team decided to keep messy data as the headline, with mitigations listed in `05_DEMO_AND_PITCH.md` section 5.1.

---

## 2. Data profile: `pizzeria-amalfi-bank-statement-2025-v6.csv`

All numbers VERIFIED by `spikes/01_csv_chf_fix/profile_csv.py` (output in the same folder).

### 2.1 Structure

| Property | Value |
|---|---|
| Rows | 1,125 transactions, 1 Jan – 31 Dec 2025, newest first |
| Format | UTF-8, `;` separator, all fields quoted, `,` decimal, dates `DD.MM.YY` |
| Columns (11) | Account Number, Booking Date, Value Date, Transaction Type, Payment Reference, Beneficiary/Payer, Counterparty Account, Bank Code, Amount, Currency, Info |
| Accounts | 1 (`DE89370400440532013000`) |
| Currencies | EUR 1,113 rows, CHF 12 rows |
| Balance column | **None.** Balance must be rebuilt |
| Booking date vs value date | Always equal |
| Duplicates | None |
| Empty counterparty account | 292 rows (all Girocard payments at the wholesale market) |

### 2.2 Flows

| Type | Rows | Sum (EUR, after CHF fix) | Pattern |
|---|---|---|---|
| Credit card payout (Commerzbank Global Pay) | 143 | +435,319 | Twice a week, 927–4,861 |
| Card settlement, debit | 335 | +109,105 | Daily, 230–461 |
| Supplier payments (Asimex, Fattoria La Vino) | 239 | −180,193 | Weekly rhythm, 550–1,095 |
| Girocard at wholesale market | 292 | −76,826 | Daily, 220–309 |
| Salaries incl. owner 3,200 | 48 | −103,200 | 28th, fixed |
| Swiss transfers to Luigi | 12 | −52,179 | 15th, 4,166.67 CHF |
| Rent | 12 | −45,600 | 1st, 3,800 |
| Direct debits (health fund 2,650 on 27th; utilities 650 on 10th; quarterly tax) | 32 | −45,100 | fixed |
| Tax office transfers (wage tax 880 monthly on 10th) | 12 | −10,560 | fixed |

Tax office total: 20 payments = 12 × 880 wage tax + 4 × 1,150 income tax prepayment (Mar/Jun/Sep/Dec 10th) + 4 × 225 trade tax (Feb/May/Aug/Nov 15th).

### 2.3 Anomalies

| # | Anomaly | Detail | Status |
|---|---|---|---|
| A1 | CHF amounts in a EUR account | 12 rows have `Amount = -4166,67`, `Currency = CHF`. The EUR value exists only in the reference text: `(4166.67 CHF @ 1.047 EUR/CHF)`. Summing `Amount` blindly gives 32,945.51 | VERIFIED |
| A2 | Hidden opening balance | Sum after the CHF fix is 30,766.35. The official year-end is 33,266.35. The difference is exactly **2,500.00**: an opening balance that is not in the file. With it, 30 Jun = −20,098.69 and the low is −22,097.60 on 3 Jul, matching the sheet and the chart | VERIFIED |
| A3 | The naive sum looks "almost right" by coincidence | 32,945.51 is only 321 away from the official figure because the two errors (+2,179 CHF, −2,500 opening) nearly cancel. A team that only eyeballs the total will not notice | VERIFIED |
| A4 | Shutdown is the whole of June, not three weeks | The sheet says "closes for 3 weeks in June". In the data there is no revenue and no supplier payment from 1 Jun to 30 Jun | VERIFIED |
| A5 | Sheet vs chart differ by one cent | 33,266.35 (sheet) vs 33,266.34 (chart label) | VERIFIED |
| A6 | Exchange rates are invented | The file uses 1.038–1.050 EUR per CHF; the real ECB rate in mid-June 2025 was about 1.07 EUR per CHF (0.9359 CHF per EUR on 13 Jun 2025) | VERIFIED (spike 02) |
| A7 | Account is already negative on 1 Jan intraday | With opening 2,500 the first booking day ends negative (rent before first settlement); 79 booking days end below zero in the year | VERIFIED |

### 2.4 What it can and cannot demonstrate

| Can | Cannot |
|---|---|
| Liquidity monitoring and forecasting with a real gap (−22k) and a recovery | Any document handling: there are no invoices or receipts |
| Recurring-flow detection (9 fixed series) | Multiple accounts, personal cards, duplicates |
| Credit-line sizing with a clear story | Receivables: revenue is card settlements, nobody "pays late" |
| Advance tax payments as known future outflows (monthly wage tax, quarterly income and trade tax) | Tax optimisation: no cost detail |
| FX exposure: 12 known CHF tranches -> simulated forward | Realistic FX rates |
| Data-quality intelligence (A1, A2) | — |

---

## 3. Transcript analysis

Two transcripts were read in full: "Autonomous CFO Challenge Discussion" (24 min, first reactions) and "Polish Invoices and VAT Automation" (70 min, the concept). Verdicts: **Keep / Change / Drop**.

### 3.1 Ideas listed in the session prompt

| # | Idea | Verdict | Reason |
|---|---|---|---|
| 1 | Central place for all invoices and spending | **Keep**, as the foundation, not the headline | It is what makes the forecast trustworthy. On its own it is a crowded category (section 5.6) |
| 2 | Photo/PDF auto-fills document fields | **Keep** | The visible "wow" of the live moment. Vision model + JSON-schema output; XML and API items need no AI |
| 3 | Employees forward to `invoices@`; detect "paid personally"; flag lost VAT and reimbursement; owner confirms; AI suggests category | **Keep** — core | Detection is a rule (no bank line on connected accounts + sender is an employee), proven in spike 04. Correction to the brainstorm: the cost **can** still be booked gross (rule PL-COST-01) |
| 4 | Private purchase from the business account -> owner withdrawal | **Change** to a flag + hint | For a sp. z o.o. it is a receivable from the shareholder, not a "withdrawal" (VERIFIED via snippet only). Show "looks private — mark as private use?" and stop there |
| 5 | Identify the paying account from the card number on the invoice | **Change** | Only some documents print the last 4 digits. Use it as one weak signal (+0.12) among several; amount/date/name do the work |
| 6 | Non-generative classifier with predefined categories | **Change** | Keep "fixed category list". Drop the separate model: no labelled data, one more model to serve. History + rules + LLM constrained to an enum gives the same guarantee (D-09) |
| 7 | Month-end insights: SQL vs AI | **Change** | Numbers by SQL (`/ledger/summary`), one sentence of wording by the LLM. Nice-to-have |
| 8 | Simple statistical forecast, no neural network | **Keep** | Proven in spike 03. Recurring schedules + weekday averages + known invoices + owner events |
| 9 | Spending limits for irregular costs as % of forecast income | **Drop** | Different product (budgeting). No link to the four challenge agents. Could reappear as one chat answer ("how much can I spend on ads?") if time remains |
| 10 | PIT return helper | **Drop** | Far from the challenge ("advance tax payments", "optimisation"), legally sensitive, the company has an accountant (transcript 69:21). Replace with a tax calendar + reserve |
| 11 | FX warning for payments sent in one month and booked the next | **Drop as described; replace** | The premise is wrong: the rule is "NBP rate of the last business day before the transaction date", not "last month's rate" (VERIFIED). The real FX topics are (a) open foreign-currency receivables/payables between invoice and payment, (b) realised FX differences. Show exposure, not predictions |
| 12 | Pull client invoices from accounting software | **Change** | Needed for the forecast (receivables). Symfonia has no hosted sandbox; Merit trial API is uncertain. Use the inFakt sandbox (free, API key) |
| 13 | Chat that generates SQL and links to rows | **Change** | Tool calling over a small fixed set of API tools first (reliable with a mid-size open model); free SQL only on read-only views as a second tool. Answers always carry evidence links |
| 14 | Export of all data | **Keep, tiny** | One endpoint (zip of CSVs), 1 hour. Supports the "owner stays in control" story |
| 15 | Host a flagship text model, a classifier and a vision model | **Change** | Prefer **one** multimodal model for reading and chat; no classifier model. Depends on the GPU (section 5.5) |
| 16 | Skip the investment agent | **Keep** | Correct for this persona. One sentence in the pitch: "after the gap closes, the same forecast shows surplus — investment agent is the natural next step" |
| 17 | Build for Poland, present as EU-generalisable | **Keep, with a twist** | Add the organisers' German pizzeria as a second company. Country rules live in one small table (`02_DATA_AND_SYNC.md` section 5). Commerzbank owns mBank, so Poland is a legitimate market |
| 18 | Risk: refocus demanded at the feedback session | **Address** | 1-minute pitch + clickable mock from fixtures by Saturday morning; architecture where the use case can be re-weighted without rebuilding (same pipeline, different cards) |

### 3.2 Other ideas found in the transcripts

| Idea (where) | Verdict | Reason |
|---|---|---|
| Upload contracts; model extracts pay terms per person (T1 04:28) | **Drop** | Confidential documents, heavy extraction, little demo value. Salaries are detected from bank history instead |
| Obsidian-style graph of accounts and cards (T1 08:31) | **Drop** | Pretty, but explains nothing a list does not |
| "Downgrade an under-used subscription" recommendation (T1 20:40) | **Change** | Usage data is not available. Feasible variant: "duplicate subscriptions" and "price went up" from recurring series. Nice-to-have |
| Could the AI cancel subscriptions by itself? (T1 20:25) | **Keep as a boundary example** | Good illustration of the control model: never without approval |
| Recommend "one company account + cards with limits" (T1 21:58) | **Change** | Not a product feature, but a good optimisation hint from the tax agent: "X PLN of VAT lost this year on private-card purchases; company cards would fix it" |
| Time tracking inside the system (T2 25:46) | **Drop** | Team already agreed; out of scope |
| Employee portal (T2 26:47) | **Drop** | Fixed decision 5 |
| Automatically reserve money for taxes (T2 38:19) | **Keep** | This is the tax-agent extension: reserve transfer to a "tax pocket", approval required, simulated |
| Route salary payments across cards/countries to save transfer fees (T2 38:31) | **Drop** | The team itself found no problem there |
| Employees' taxes in several countries (T2 41:16) | **Drop** | Team agreed: too specific |
| Mascot / game to make finance "fun" (T2 68:28) | **Change** | "Fun and easy" = plain language, a cash "weather" indicator, one-tap approvals, celebratory "all clear" state. No game |
| Data protection with Red Hat tooling for bonus points (T2 31:15) | **Change** | Guardrails are one of the bonus options; choose by effort (section 5.5) |
| Use a Claude API key on the cluster for the app (T2 31:34) | **Drop** | Violates hard criterion 2. Allowed only as a coding assistant |
| "Plan today, start implementation tomorrow evening" (T2 62:22) | **Drop — dangerous** | See finding 1. Model deployment and a walking skeleton must start today |
| Ask organisers what "credit facilities" means (T2 27:52) | **Resolved** | It means bank credit products for a business: overdraft/credit line, working-capital loan (section 4.3, H1) |
| "Is VAT refunded by ZUS at year end?" (T2 44:49) | **Resolved — wrong** | VAT is settled monthly with the tax office (JPK_V7 by the 25th): output VAT minus deductible input VAT. ZUS is social security. PIT is a separate annual return |
| "If a Pole buys from an Estonian firm, is tax paid twice?" (T2 45:35) | **Resolved** | B2B cross-border service: reverse charge, the buyer self-assesses Polish VAT, neutral (PL-VAT-03) |

---

## 4. Feasibility matrix

Capacity basis: 6 people × about 24 working hours each before Sunday 10:00 = about 144 person-hours; minus integration, rehearsal and pitch = **about 100 person-hours of features**.
Columns: Hours = build estimate. Verdict: **D** doable / **R** doable in a reduced form / **N** not doable.

### 4.1 Fixed decisions

| Fixed decision | Hours | Data / API really available | Legal / tax | Demo value | Judging fit | Verdict | Fallback | Evidence |
|---|---|---|---|---|---|---|---|---|
| F1 Messy SME data as the core selling point | 35 (generator 12, extraction 10, matching 13) | We generate it; ground truth included | Rules verified where encoded | High (live moment) | Medium alone, high when it visibly changes the liquidity number | **R** — keep. Team decision: it stays the headline of the pitch; every step must end in a number on the cash forecast | If extraction is weak: KSeF XML + PDF with text layer only; photos go to "needs review" | Spike 04; section 5.6 |
| F2 Every source through a real running connector | 22 for 3 must-have + 2 should-have | Mailbox, NBP, inFakt sandbox, Commerzbank sandbox: self-service. Polish bank sandboxes: not available. KSeF test: available but heavy | — | High (Sources page with live "last synced") | High for Red Hat ("really running") | **R** — 3 must (mail, bank simulator, NBP), 2 should (inFakt, Commerzbank sandbox), KSeF API as stretch | Each connector has a fallback (table in `02_DATA_AND_SYNC.md` 3.1) | Agent research; spike 02 |
| F3 Liquidity agent end to end | 22 (ledger 5, forecast 7, alerts + credit sizing 4, scenarios 3, executor 3) | Own data + pizzeria CSV | Credit terms are illustrative, labelled as such | Very high | Very high | **D** | Pizzeria-only liquidity demo (works from one CSV) | Spike 03 |
| F4 Sandboxes and synthetic data only | 0 | — | Required | — | Safe | **D** | — | Dataset spec |
| F5 Owner-only product, dashboard + embedded chat | 24 (dashboard 14, chat 10) | — | — | High | High (theme fit) | **D** — chat reduced to 5 tools | Chat cut to 3 canned questions with real tool calls | — |

### 4.2 Ideas

| Idea | Hours | Data / API | Legal / tax | Demo | Fit | Verdict | Evidence |
|---|---|---|---|---|---|---|---|
| Photo/PDF field extraction | 10 | Vision model on cluster | n/a | High | Medium | **D** (accuracy UNVERIFIED until tested on the cluster) | OCR spike not run |
| Paid-personally detection + VAT + reimbursement | 6 | Derived | PL-VAT-01, PL-COST-01 verified; PL-REIMB-01 hint | High | Medium–high (tax "optimisation") | **D** | Spike 04 |
| Private use from business account | 1 | Derived | Hint only | Low | Low | **R** (flag) | — |
| Card-number matching | 0.5 | Sometimes present | n/a | Low | Low | **R** (weak signal) | — |
| Classifier model | 8+ | No training data | n/a | Low | Low | **N** as a separate model; **D** as constrained LLM | D-09 |
| Month-end insights | 3 | Ledger | n/a | Medium | Medium | **R** (nice-to-have) | — |
| Statistical forecast | 7 | Ledger + bank | n/a | Very high | Very high | **D** | Spike 03 |
| Spending limits | 4 | Forecast | n/a | Low | Low | **N** (cut) | — |
| PIT filing helper | 15+ | Forms change yearly | High risk | Low | Low | **N** (cut) | — |
| Tax reserve + calendar | 4 | Ledger + calendar | PL-CAL-01..03 verified | Medium | High (tax agent, partial) | **D** | Research |
| FX month-boundary warning | — | — | Premise wrong | — | — | **N** | PL-FX-01 |
| FX exposure + simulated forward | 4 | NBP + open invoices | Info only | Medium | High (FX agent, partial) | **R** (nice-to-have) | Spike 02 |
| Accounting-software sales invoices | 4 | inFakt sandbox | n/a | Medium (receivables feed the forecast) | High | **D** | Research |
| Chat with SQL + row links | 10 | Model with tool calling | n/a | High | High | **R** (5 tools + guarded SQL) | — |
| Data export | 1 | — | n/a | Low | Medium | **D** | — |
| Three models on the cluster | — | GPU unknown | n/a | — | Risky | **R** (one model) | Section 5.5 |
| Investment agent | — | — | — | — | — | **N** (skip; one pitch sentence) | — |
| Poland first, EU later | 0 | — | — | — | Medium | **D** (+ German pizzeria) | — |

### 4.3 Hypotheses

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | "Credit facilities" = bank credit line / overdraft / short-term working-capital loan | **Confirmed**: pre-agreed arrangements to borrow up to a limit — overdraft, revolving line, factoring line, working-capital loan. Commerzbank's SME overdraft is the "Gewerbekredit" (from 5,000 EUR); mBank's is "kredyt w rachunku bieżącym" | VERIFIED product pages ([Commerzbank](https://www.commerzbank.de/unternehmerkunden/finanzierungen/gewerbekredit/), [mBank](https://www.mbank.pl/firmy/kredyty/biezace-zarzadzaniem-firma/kredyt-w-rachunku/)); the definition itself is general knowledge. Still ask the judges (Q4) |
| H2 | Pizzeria: June shutdown, low about −22k early July, year-end +33.3k; predictable weeks ahead | **Confirmed with a condition**: lowest −22,097.60 on 3 Jul; predictable 7 weeks ahead only with the closure as an input | VERIFIED (spikes 01, 03) |
| H3 | CHF quirk: naive sum about 32,945 instead of 33,266.35 | **Partly right**: naive sum is 32,945.51, but the correct reconciliation is CHF fix (30,766.35) + hidden opening balance 2,500.00 | VERIFIED (spike 01) |
| H4 | Pizzeria is German, team targets Poland: decide | **Decision**: Polish synthetic company for the messy-data story; pizzeria as second company and regression test | D-11 |
| H5 | CHF tranches are a natural FX-hedging case | **Confirmed**: 12 known tranches of 4,166.67 CHF -> exposure schedule -> simulated forward. Rates in the file are invented | VERIFIED (spikes 01, 02) |
| H6 | Polish tax uses the NBP average rate of the last business day before the transaction, not "last month's rate" | **Confirmed** (income tax and VAT) | VERIFIED secondary ([source](https://poradnikprzedsiebiorcy.pl/-przeliczenia-kosztu-w-walutach-obcych-kursy-walut-a-data-faktury)); statute text itself not fetched |
| H7 | KSeF rolls out in 2026; official test environment with an API | **Confirmed**: issuing mandatory since 1 Feb 2026 (large) and 1 Apr 2026 (others); very small sellers may stay outside until 31 Dec 2026. Test API at `api-test.ksef.mf.gov.pl`. Paper/PDF still matter: foreign suppliers, consumer receipts and till receipts with NIP are outside KSeF in 2026 | VERIFIED ([gov.pl](https://www.gov.pl/web/finanse/drugi-etap-wdrozenia-krajowego-systemu-e-faktur), [CIRFMF](https://github.com/CIRFMF/ksef-docs/blob/main/srodowiska.md)); "outside KSeF" list via snippets |
| H8 | Receipt with NIP ≤ 450 PLN = simplified invoice; reimbursement on a company invoice is not employee income; paying as hours is; VAT only from an invoice to the company | **Mostly confirmed**: 450 PLN rule true for 2026; VAT rule true; salary = taxable true (basic rule, no source fetched); reimbursement-not-income is the prevailing view with contrary rulings -> hint only | See `02_DATA_AND_SYNC.md` section 5 |
| H9 | Advance tax payments fit the forecast as a tax reserve; PIT filing helper is off-topic | **Confirmed** (design judgement) | Challenge card: "coordinates advance tax payments" |
| H10 | Existing products overlap heavily; gap = personal-card purchases + several accounts + documents -> one approved ledger -> forecast | **Confirmed, and the overlap is heavier than assumed**: every piece exists separately, mBank itself ships a 4-week forecast, and reimbursement is largely solved by spend-card products. The gap is the **chain** and two specifics (wrong buyer on the invoice; bank-agnostic data ending in a bank action) | Section 5.6 |

---

## 5. Research

### 5.1 Bank sandboxes and open banking

| Option | Sign-up | Own test data? | Verdict for 43 hours |
|---|---|---|---|
| Polish banks (PolishAPI) | TPP application or eIDAS certificate needed (PKO BP VERIFIED; others UNVERIFIED) | — | No |
| GoCardless Bank Account Data | New sign-ups disabled — VERIFIED | — | No |
| Commerzbank developer portal | Free self-registration; OAuth2; accounts, payments, corporate payments, securities APIs — VERIFIED | **No, static data** — VERIFIED | Yes as a read-only second connector (sponsor fit), time-boxed |
| Enable Banking mock ASPSP | E-mail link; usable before any contract — VERIFIED | Yes, entered in a control panel — VERIFIED | Backup for the above |
| Revolut Business sandbox | Pre-generated keys; create own transactions; webhooks — VERIFIED. Instant sign-up UNVERIFIED | Yes | Technically best hosted option; not chosen (competitor optics, request signing) |
| Wise sandbox | V1 retired 30 Jun 2026; V2 access unclear — VERIFIED | Partly | No |
| Open Bank Project in a container | Self-hosted JVM app, 1–2 h set-up — VERIFIED from README | Yes | No: our 150-line simulator does the same job |
| adorsys XS2A ModelBank | Needs 5 GB+, old Java/Node stack — VERIFIED | Yes | No |
| **Own PSD2-shaped simulator** | 0 | Yes | **Chosen as the demo bank** (`contracts/bank-sim-api.md`) |

Sources: [Commerzbank portal help](https://service-corporates.commerzbank.com/applications-and-projects/), [Enable Banking sandbox](https://enablebanking.com/docs/api/sandbox/), [Revolut Business API](https://developer.revolut.com/docs/api/business), [Wise sandbox migration](https://docs.wise.com/guides/developer/environments/sandbox-v2-migration), [GoCardless notice](https://bankaccountdata.gocardless.com/new-signups-disabled), [PKO BP](https://developers.pkobp.pl/en/page/knowledgeBase), [OBP](https://github.com/OpenBankProject/OBP-API).

### 5.2 KSeF

| Fact | Status |
|---|---|
| Mandatory issuing: 1 Feb 2026 (sales over 200m PLN), 1 Apr 2026 (others); sellers with at most 10,000 PLN gross invoiced per month may wait until 31 Dec 2026 | VERIFIED ([gov.pl](https://www.gov.pl/web/finanse/drugi-etap-wdrozenia-krajowego-systemu-e-faktur)) |
| Penalties deferred for 2026; extension to end of 2027 passed by the Sejm on 6 Nov 2026, later steps not confirmed | VERIFIED ([KPMG](https://kpmg.com/pl/pl/wiedza/podatki/alert-podatkowy-przedluzenie-odroczenia-kar-za-bledy-w-stosowaniu-ksef-do-konca-2027-r.html)) |
| Test API `https://api-test.ksef.mf.gov.pl`; self-signed certificates and made-up NIPs allowed in TEST; data is shared between integrators | VERIFIED ([environments](https://github.com/CIRFMF/ksef-docs/blob/main/srodowiska.md), [test data](https://github.com/CIRFMF/ksef-docs/blob/main/dane-testowe-scenariusze.md)) |
| Auth: challenge -> XAdES-signed request -> poll -> redeem token; JWT minutes, refresh up to 7 days | VERIFIED ([auth](https://github.com/CIRFMF/ksef-docs/blob/main/uwierzytelnianie.md)) |
| Buyer download: `POST /invoices/query/metadata`, async encrypted `POST /invoices/exports`, `GET /invoices/ksef/{number}` | VERIFIED ([incremental download](https://github.com/CIRFMF/ksef-docs/blob/main/pobieranie-faktur/przyrostowe-pobieranie-faktur.md)) |
| Official clients: C# and Java only; Python clients are community packages | VERIFIED (CIRFMF GitHub); community packages not vetted |
| Schema FA(3), namespace `http://crd.gov.pl/wzor/2025/06/25/13775/` | VERIFIED ([XSD folder](https://github.com/CIRFMF/ksef-docs/tree/main/faktury/schemy/FA)) |

Meaning for "paper invoices": domestic B2B invoices now arrive as structured XML, which is easy. The mess that remains — and that our product targets — is everything KSeF does not cover: foreign SaaS invoices (PDF), receipts, purchases in a private name, and the link between any document and the money.

### 5.3 Accounting software APIs

| Product | Sandbox / trial | Auth | Verdict |
|---|---|---|---|
| **inFakt** | Dedicated free sandbox with self-registration — VERIFIED ([docs](https://docs.infakt.pl/koncepcje/sandbox/)) | API key header | **Chosen** |
| Fakturownia | 30-day trial; API on trial UNVERIFIED | Bearer token | Backup |
| Merit Aktiva / 360 Księgowość | One API for EE and PL — VERIFIED; API on trial UNVERIFIED | HMAC-signed query | Later (Estonia story) |
| iFirma | Docs VERIFIED; trial terms UNVERIFIED | HMAC header | No |
| wFirma | Docs not readable | — | No |
| Symfonia | On-premise WebAPI with licence; no hosted sandbox found — UNVERIFIED | — | No |

### 5.4 Exchange rates

| API | Result | Status |
|---|---|---|
| NBP `api.nbp.pl` table A | No key; about 0.3 s; 404 on non-business days; range query limited to 93 days | VERIFIED (spike 02) |
| frankfurter.dev (ECB reference rates) | No key; about 0.3 s; silently returns the previous business day on weekends | VERIFIED (spike 02) |
| ECB SDMX `data-api.ecb.europa.eu` | Works; 14 s for one small query in the spike | VERIFIED (spike 02) — not for interactive use |

### 5.5 Platform, models and document parsing

Read by a research agent through a browser (docs.redhat.com blocks automated fetching). Nothing here was run by us.

| Topic | Finding | Status |
|---|---|---|
| vLLM | RHOAI 3.5 ships vLLM 0.24.0; default GPU ServingRuntime for KServe; RawDeployment supported; tool calling needs `--enable-auto-tool-choice --tool-call-parser <name>`; structured output via `response_format: json_schema` (`guided_json` was removed) | VERIFIED ([release notes](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html-single/release_notes/index), [vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/), [structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)) |
| "ogx" | The renamed Llama Stack ("Open GenAI Stack"), Technology Preview. `OGXServer` CR, needs its own PostgreSQL, OpenAI-compatible API on port 8321 incl. `/v1/responses`; MCP tool runtime enabled by default (Developer Preview) | VERIFIED in RHOAI 3.5 docs; exact MCP tool syntax UNVERIFIED |
| MCP catalog | Technology Preview; needs `mcplifecycleoperator: Managed` (default off) | VERIFIED in docs |
| MaaS gateway | Needs llm-d with auth, Connectivity Link + Kuadrant, a Gateway with TLS patches, user workload monitoring, own PostgreSQL; models must be `LLMInferenceService` | VERIFIED in docs. Estimate 4–8 h, high risk on one node |
| llm-d | Scheduler in front of vLLM replicas; Gateway defaults to `LoadBalancer` | VERIFIED in docs. No benefit with one GPU and one replica |
| NeMo Guardrails | Included in RHOAI; `NemoGuardrails` CR; quick start uses PII (Presidio) and regex rails without an LLM; app calls `/v1/chat/completions` on the guardrails route | VERIFIED in docs. Estimate 1.5–3 h |
| OpenShell | Sandbox runtime for autonomous coding/personal agents; experimental on OpenShift; needs cluster-admin and privileged SCC | VERIFIED ([guide](https://github.com/opendatahub-io/agent-ops/blob/main/guides/getting-started-openshell-openshift.md)) |
| MLflow | Built-in component (`mlflowoperator`), `MLflow` CR, server 3.13; workbenches auto-configured; `mlflow.openai.autolog()` and `mlflow.genai.evaluate` exist upstream | VERIFIED in docs + [MLflow docs](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/openai/). Red Hat docs do not mention autolog — UNVERIFIED that it works unchanged |
| Open multimodal models (Apache-2.0) | Qwen3.5-9B (FP8 14 GB), Qwen3.8-27B (FP8 30.9 GB), Mistral Small 3.1/3.2 24B, Gemma 4; Granite 4.2 has no vision and does not list Polish among tested languages; granite-vision-4.1-4b is extraction-only | VERIFIED on Hugging Face cards by the research agent |
| Model availability on the cluster | Red Hat's modelcar catalog has Qwen3.8-27B (BF16 and NVFP4), Granite 4.0, Mistral Small 3.1 quantised; the FP8 Qwen builds come from Hugging Face | VERIFIED ([quay catalog](https://quay.io/repository/redhat-ai-services/modelcar-catalog), [validated models](https://docs.redhat.com/en/documentation/red_hat_ai/3/html-single/validated_models)) |
| Docling | `docling-serve-cpu` image (4.4 GB), REST `/v1/convert/source`; OCR language must be set explicitly; CPU OCR can take over 30 s per page with some engines | VERIFIED ([docling-serve](https://github.com/docling-project/docling-serve), [OCR docs](https://docling-project.github.io/docling/concepts/OCR/)); speed UNVERIFIED |
| Our GPU | Unknown | UNVERIFIED — first command on the cluster |
| What is pre-enabled on our cluster | Unknown | UNVERIFIED — `oc get datasciencecluster -o yaml` |

Conclusions: one multimodal Qwen model served by vLLM (size by GPU); Docling on CPU only for PDFs with a text layer; photos go to the vision model; bonus set = vLLM + MLflow + Jupyter (+ NeMo Guardrails; OGX/MCP as a stretch). Details and memory math: `01_SOLUTION.md` sections 6.3 and 7.

### 5.6 Existing solutions and the real gap

Coverage: **a** capture/OCR, **b** bank feed + reconciliation, **c** out-of-pocket reimbursement, **d** cash forecast, **e** financing offer, **f** AI agent/chat.

| Product | a | b | c | d | e | f | Note | Status |
|---|---|---|---|---|---|---|---|---|
| **mBank mOrganizer finansów / mKsięgowość** | partly | yes | no | **yes (4 weeks, shortfall alerts)** | not in the tool | no | Commerzbank's own subsidiary already forecasts for micro firms | VERIFIED ([mBank](https://www.mbank.pl/firmy/ksiegowosc/morganizer-finansow/)) |
| SaldeoSMART | yes | yes | advances only | no | no | — | KSeF free | VERIFIED ([help](https://pomoc.saldeosmart.pl/hc/pl/articles/37636576008861)) |
| wFirma | yes (AI) | yes (AI import) | — | no | no | partly | Owner approves each entry | VERIFIED ([help](https://pomoc.wfirma.pl/-ai-w-systemie-wfirma-pl-poznaj-moc-sztucznej-inteligencji)) |
| inFakt, Fakturownia, iFirma | yes | yes | — | — | — | — | Invoicing/bookkeeping | UNVERIFIED (review blogs only) |
| Symfonia eDokumenty | yes | — | **yes, linked to KSeF** | — | — | chat | Larger SMEs | VERIFIED ([page](https://symfonia.pl/edokumenty/wydatki-pracownicze/)) |
| Comarch (Optima, Betterfly) | yes | yes | — | not found | — | AI agents since Sep 2026 | | VERIFIED ([article](https://bezprawnik.pl/agenci-ai-comarch/)) |
| Pleo, Spendesk, Moss, Circula, Rydoo, Expensify | strong | card lines | **strong** | no | no | some | Polish availability UNVERIFIED | Pleo reimbursements VERIFIED ([help](https://help.pleo.io/en/articles/5183605)) |
| Payhawk | strong | yes | strong | — | — | — | In Poland with PLN cards and KSeF intake | VERIFIED ([blog](https://payhawk.com/blog/payhawk-expands-in-poland)) |
| Qonto | yes | own account | yes | **yes, scenarios** | **yes, invoice financing** | **AI agents (Apr 2026)** | Inside its own bank account; Poland UNVERIFIED | VERIFIED ([news](https://thepaypers.com/fintech/news/qonto-rolls-out-ai-agents-for-banking-operations-across-600000-sme-customers)) |
| Finom | yes | own account | — | — | credit lines (DE) | chat beta | | VERIFIED ([news](https://thepaypers.com/fintech/news/finom-expands-its-credit-offering-in-germany)) |
| Revolut Business | yes | own account | paid add-on | — | — | AI matching | Polish page exists | VERIFIED ([page](https://revolut.com/pl-PL/business/expense-management)) |
| Agicap, Commitly, Tidely, Helu | — | yes | — | **strong** | — | some | Assume clean books; mid-market or German | VERIFIED ([G2](https://www.g2.com/products/agicap/features), [OMR](https://omr.com/de/reviews/contenthub/beste-liquiditaetsplanung-software)) |
| sevdesk, Lexware Office, Candis | yes | yes | — | — | — | — | German; sevdesk and Candis are official Commerzbank partners | VERIFIED ([partner page](https://www.commerzbank.de/unternehmerkunden/partnerangebot/)) |
| Zeni, Puzzle, Truewind | yes | yes | — | some | — | "AI CFO" | US only | VERIFIED ([Zeni](https://www.zeni.ai/blog/zeni-vs-truewind)) |

Honest reading:

1. **Capture and reconciliation are commodity.** Do not pitch them.
2. **Reimbursement is mostly solved** — for companies that adopt a spend-card product. It is not solved for what actually happened without one: private cards and the wrong buyer on the invoice.
3. **Forecasting exists**, including at mBank. What is missing is a forecast built on a ledger that contains hidden liabilities, with every number traceable, ending in a bank action.
4. **Not found in one product:** several banks and currencies + owner's private card + e-invoices + photo receipts + accounting export -> deduplicated, owner-approved ledger -> forecast -> pre-filled credit request. Neobanks do parts of it only inside their own account.
5. **"Invoice issued to the employee instead of the company"**: no vendor was found that flags it, prices the lost VAT and proposes the fix. Absence of evidence, not proof — UNVERIFIED.
6. **White space at the sponsor:** Commerzbank has an avatar assistant for retail (Ava) and is piloting agentic AI, but no SME-facing agent was found — VERIFIED as "none found" ([press release](https://www.commerzbank.de/konzern/newsroom/pressemitteilungen/ki-partnerschaften.html)).

Bank products to name in the demo:

| Bank | Product | Facts | Status |
|---|---|---|---|
| Commerzbank | **Gewerbekredit** (overdraft / Kontokorrent) | From 5,000 EUR; decisions up to 100,000 EUR in the advisory meeting; no rate published; inputs: two annual statements, current BWA, account statements, credit-bureau data | VERIFIED ([page](https://www.commerzbank.de/unternehmerkunden/finanzierungen/gewerbekredit/)) |
| Commerzbank | FX Live Trader | 100+ currency pairs; minimum sizes UNVERIFIED | VERIFIED ([page](https://www.commerzbank.de/unternehmerkunden/zahlungsverkehr/devisenhandel/)) |
| Commerzbank | Card acquiring is called **Commerz Globalpay** (the CSV says "Commerzbank Global Pay") | | VERIFIED |
| mBank | **Kredyt w rachunku bieżącym** | Up to 500,000 PLN; nominal 7.18% (promo margin 3.7%); 3% renewal fee; renews every 12 months | VERIFIED ([page](https://www.mbank.pl/firmy/kredyty/biezace-zarzadzaniem-firma/kredyt-w-rachunku/)) |
| mBank | mPlatforma walutowa (spot and forward) | | VERIFIED via snippet |

Useful domain detail: the KSeF FA(3) schema has a `Podmiot3` role 11 "Pracownik" for purchases made by an employee while the company stays the buyer — the correct process going forward (VERIFIED, [EY](https://www.ey.com/pl_pl/insights/tax/wydatki-pracownicze-a-ksef)). Our "how to stop losing VAT" hint points to it.

Collabothon pattern: the 2025 Grand Award went to a voice banking assistant usable without a smartphone; the Audience Award to a transaction-risk "guardian" with a live demo — UNVERIFIED (social-media snippets). Pattern: inclusion, a concrete user, a working demo.

---

## 6. Spikes

See `spikes/README.md` for commands, timings and outputs.

| Spike | Riskiest claim it tests | Result |
|---|---|---|
| 01 | "We can parse the organisers' file and reproduce their numbers" | Yes, exactly, after finding two traps |
| 02 | "Rates are available without keys, including the Polish tax rule" | Yes |
| 03 | "A simple explainable forecast is good enough" | Yes with owner events (1.2% error); no without |
| 04 | "Rule-based matching can untangle the mess" | Yes on synthetic data (97–100%) |
| — | "Receipt photos can be read in seconds" | **Not tested** (package downloads blocked). Highest remaining technical uncertainty |

---

## 7. Cut list (do not reopen)

| Cut | Why |
|---|---|
| PIT / tax-return filing helper | Off-challenge, legal risk, accountant exists |
| Spending limits / budgeting | Not one of the four agents |
| Investment agent | Does not fit the persona; one sentence in the pitch |
| Employee portal, time tracking, contract upload | Out of scope by team decision or low value |
| Account/card graph visualisation | No decision value |
| Separate classifier model | No data, extra serving cost; constrained LLM instead |
| Neural / time-series forecasting models | Not needed (spike 03), not explainable |
| FX rate prediction and the "month-boundary" warning | Premise wrong; prediction is guesswork |
| Polish bank sandboxes (PolishAPI), GoCardless, Wise, Revolut, OBP, adorsys | Not available in time or not worth it |
| n8n, Kafka, Redis | More moving parts on a single node, no benefit |
| KSeF **API** connector | Stretch only; XML ingestion stays |
| Symfonia / Merit connectors | No sandbox in time; inFakt instead |
| Multi-country payroll tax logic | Too specific |
| Real execution of anything | Everything is simulated and labelled |
| Authentication, multi-tenancy, user management | Not judged; single demo tenant |
| Mobile app | A responsive web page is enough |
| Quarkus + LangChain4j, llm-d | See section 5.5 |
