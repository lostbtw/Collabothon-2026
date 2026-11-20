# 05 — Demo, pitch and critic pass

Self-contained. Owner: role 6 (pitch) with role 5 (demo operator).
Working product name: **Ordo**. Demo companies: **Borsuk Labs sp. z o.o. (SAMPLE)** and the organisers' **Pizzeria Amalfi**.
Schedule (VERIFIED, [collabothon.eu/schedule](https://www.collabothon.eu/schedule/)): feedback sessions Sat 14:00–18:00; coding ends Sun 10:00; presentations Sun 10:30–15:00.
Pitch length assumed 3 minutes — UNVERIFIED, ask the organisers (Q2 in `06_RISKS_AND_QUESTIONS.md`). A 5-minute stretch is marked.
Event judging criteria (VERIFIED, [rules](https://www.collabothon.eu/rules/)): fit to challenge / business value, technical implementation / complexity, innovation, design.

---

## 1. One sentence, three sentences

Pitch order decided by the team on 20 Nov: **messy data first, liquidity agent second** (see `DECISIONS.md` R-01).

**One sentence:** Ordo turns a small company's financial chaos — several accounts, private cards, receipts on phones — into one ledger the owner trusts, and uses it to warn about cash gaps weeks ahead and prepare the fix.

**Three sentences:**
1. Small-company money is messy: several accounts, costs paid from private cards, receipts on phones, unpaid client invoices — so nobody knows the real numbers, and the bank balance lies.
2. Ordo's agents collect all of it through live connectors, remove duplicates, work out who really paid, and tidy it into one ledger the owner approves.
3. On that ledger the liquidity agent forecasts cash day by day; when a gap is coming it explains why, proposes a credit line with alternatives, and acts only after the owner approves — in this build, as a clearly labelled simulation.

---

## 2. The 1-minute version (feedback session, Saturday 14:00–18:00)

Bring: the clickable mock running on fixtures (or the real skeleton if ready) and the pizzeria chart.

> "Your challenge card says small-business owners run finance themselves and miss things. We think they miss things because their data is a mess — so that is what we fix first.
>
> Take a real 7-person company: two bank accounts, the owner's private card, employees buying tools with their own cards, receipts on phones, e-invoices, an invoicing tool. Our agents pull all of it through live connectors, read every document, remove duplicates, match documents to payments and work out who really paid. Nothing enters the books until the owner approves.
>
> On that clean ledger we run your **liquidity agent** end to end. The bank says 38,000; the truth is a 28,000 hole in three weeks, because of money owed to employees, tax coming due and a late client. The agent warns, explains, proposes a credit line with alternatives, and the owner approves — executed as a simulation.
>
> We also ran your pizzeria file: we found two traps in it — Swiss francs booked in a euro account and a missing opening balance — and predicted the July low seven weeks ahead, once the owner says 'we are closed in June'.
>
> Every agent action is labelled: *done on its own*, *recommended*, *needs your approval*, *simulated*.
>
> Two questions for you: is messy input data a problem you see with your SME clients? And is a credit line on the current account the 'credit facility' you have in mind?"

Why this order: it opens with the team's selling point (the mess), names **their** liquidity agent as what the clean data is for, proves it on **their** file, and ends by asking the judges to steer us while there is still time.

If they say "refocus": the pipeline does not change, only which cards we build. Options ready to offer on the spot:

| They say | We answer | Cost |
|---|---|---|
| "Too much invoice handling" / "this is not one of the four agents" | Switch to plan B order: open on the dashboard ("bank says 38,400 — is he fine?"), one receipt in 30 s, then 90 s on forecast, credit line, scenarios and approval | 0 h, it is a script change. Decide at the Saturday 18:00 meeting |
| "Show Commerzbank products" | The credit card already names them: mBank "kredyt w rachunku bieżącym" for Borsuk Labs, Commerzbank "Gewerbekredit" (from 5,000 EUR) for the pizzeria. Add the FX forward card on the pizzeria's CHF tranches | 3–4 h for the FX card |
| "Poland is not interesting" | Lead with Pizzeria Amalfi; Borsuk Labs becomes "and here is a messier company" | 0 h |
| "Where is the tax agent?" | Tax reserve card + tax calendar are in the plan as extension 1 | already planned |

---

## 3. The 3-minute demo script

Cast: **Presenter** (speaks), **Operator** (clicks, role 5), **Phone** (a third teammate with a printed SAMPLE receipt).
Screen: the app on the cluster route URL (visible in the address bar — proof it runs on OpenShift).
Demo clock: Sat 21 Nov 2026. Company: Borsuk Labs.

| Time | Screen | Presenter says | Operator / Phone | Control level shown |
|---|---|---|---|---|
| 0:00–0:20 | Sources page: mailbox, 2 bank accounts, owner's card, invoicing tool, NBP — each with "synced 8 s ago", counters ticking | "Tomasz runs a 7-person software studio. No CFO. His money information lives in five places: two bank accounts, his own card, his team's phones and a mailbox nobody reads. Ask him what the company spent last month — he cannot tell you. Ordo can. And nothing here was uploaded: connectors pull it all, on their own schedule." | **Phone (at 0:10):** photographs the receipt and forwards it to the invoices@ mailbox | analysed autonomously |
| 0:20–0:45 | "What I did on my own" feed: 1,480 items read, 61 duplicates merged, 212 payments matched. Open one merged purchase: e-invoice XML + PDF + photo -> one record. Open one cross-currency match: 45 USD invoice <-> 180.62 PLN card line | "This is what the agents did without asking. One hosting invoice arrived three times — as an e-invoice, a PDF and a photo. Ordo kept one. A 45-dollar subscription was matched to a 180-złoty card payment using the central-bank rate. Reading, de-duplicating, matching: no decisions, no money moved." | Scroll the feed; open the two examples | analysed autonomously |
| 0:45–1:15 | Toast "New receipt from Jan". Opens: photo left, fields right. Banner: "Paid privately by Jan — no matching payment on any company account". Flags: "No company tax number: 242.90 PLN VAT cannot be recovered" | "And there is the receipt we just sent. Read by the model on this cluster. Ordo sees no matching payment on any company account, and the sender is an employee — so Jan paid himself. The company owes him 1,299, and because the receipt has no company tax number, 243 złoty of VAT is gone." | Click the toast; hover the reasons | recommendation |
| 1:15–1:40 | Card "Pay Jan back 1,299.00 PLN" — badge **Needs your approval · Simulated**. Click Approve. Counter "VAT lost this year" ticks up. Forecast low point animates −6,571 -> −7,870 | "Today this would be paid as extra hours — taxed as salary. Ordo proposes a proper reimbursement, and nothing enters the books until Tomasz approves. He does. Two things happen: the running total of VAT lost this way goes up — that is the tax optimisation — and the cash forecast moves. A liability no bank statement shows is now in the plan." | Approve | approval required, simulated |
| 1:40–2:15 | Forecast chart with red zone 30 Nov–7 Dec. Card "Open a 30,000 PLN credit line before 30 November". Open "Why?": three reasons, each with a link. Click the Nordwind reason -> invoice + "pays 23 days late on average (6 invoices)". Show alternatives and the stress toggle | "Because the data is now true, the liquidity agent can do its job. The bank says 38,400. But salaries leave on the 30th and the biggest client usually pays 23 days late. Ordo proposes a credit line, shows the calculation, the cheaper alternative — send a reminder first — and the bad case if the client slips again. Every number links to the rows behind it." | Open explanation, click one evidence link, toggle stress case | recommendation |
| 2:15–2:30 | Edit 30,000 -> 25,000, Approve. Result: "SIMULATED — application SIM-CL-2026-0007 accepted by the sandbox bank". Chart redraws above zero | "Tomasz stays in charge: he lowers it to 25,000 and approves. In production this would be an overdraft request to his bank — at mBank, a 'kredyt w rachunku bieżącym'. Here it goes to a sandbox bank, clearly marked simulated." | Edit, approve | approval required, simulated |
| 2:30–2:48 | Switch company to Pizzeria Amalfi. Data-quality note: "12 CHF lines converted; opening balance 2,500 inferred". Chat: "We are closed for all of June." Forecast drops to −21.8k; credit card appears | "Same agents, your data. Even your clean file had two traps, and Ordo caught both. Then one sentence from the owner, and it predicts the July low within 1.2% — seven weeks ahead." | Type (or paste) the sentence | analysed + recommendation |
| 2:48–3:00 | Slide: architecture on OpenShift AI + the four control levels | "All of it runs on our OpenShift AI cluster: open model served with vLLM, traces in MLflow. Ordo does not replace the accountant. It gives every owner — whatever their age or finance skills — the true picture, a CFO's foresight, and the last word." | Slide | — |

Time split: messy data 0:00–1:40 (100 s), liquidity agent and pizzeria 1:40–2:48 (68 s). The liquidity flow is still shown complete (forecast -> explanation -> approval -> simulated execution), because the challenge requires one agent end to end.

5-minute stretch (only if the slot allows): add (a) chat question "Why will I be short in December?" answered with evidence and the SQL behind it; (b) tax card "Set aside 14,300 PLN for VAT on the 25th"; (c) the MLflow trace of the receipt extraction, shown to the Red Hat judge.

### 3.1 Timing budget of the live moment

| Step | Budget | Measured |
|---|---|---|
| Phone -> mailbox delivery | 2–8 s | UNVERIFIED |
| Poll interval | 0–20 s (average 10) | by design |
| Vision extraction | 5–10 s | UNVERIFIED until tested on the cluster |
| Match + recommendation + forecast | 2 s | spike 03/04: under 0.2 s of compute |
| **Total** | **about 15–35 s** | rehearse 5 times; the phone sends at 0:10 and the toast is needed at 0:45, so the script has 35 s of talk in between |

### 3.2 Fallback ladder for the live moment

| If | Then |
|---|---|
| Mail is slow (more than 40 s) | Operator opens the receipt forwarded **2 minutes before the pitch** by a second teammate (already processed, marked unread). Presenter: "here is one from a minute ago" |
| Mailbox connector is down | Send the same photo to the Telegram bot (second channel, same pipeline) |
| Vision model fails or misreads | Document lands in "needs review" with the image; operator corrects one field in 3 s — "and when it is unsure, it asks" (this is a feature) |
| Cluster or network down | 90-second screen recording made Saturday night, plus the cluster console screenshot. Say so openly |
| Wi-Fi blocks the phone | Phone uses mobile data; the mailbox is on the internet, not on the venue network |

Rule: the recording is made as soon as the flow works once. Not later.

---

## 4. What the UI must make obvious (theme: "for all generations")

| Principle | Concrete element |
|---|---|
| One glance | "Cash weather": sunny / cloudy / storm with "in 9 days" — the only playful element, understood by anyone |
| Plain words | Card titles are instructions ("Pay Jan back 1,299.00 PLN"), never jargon ("Reimbursement liability detected") |
| Four labels everywhere | Coloured badge on every card and feed line: *Done on its own* (grey), *Recommendation* (blue), *Needs your approval* (amber), *Simulated* (purple outline) |
| Why? is one tap | Every card has "Why?" -> reasons, calculation, evidence links, alternatives |
| Nothing irreversible by accident | Approve asks once, shows exactly what will happen, includes the word SIMULATED |
| Two depths | Toggle "Simple / Detailed". Simple hides tables and shows sentences |
| Language | EN for the pitch; PL and DE toggle if time (LLM wording + static labels) — nice-to-have |
| Large targets | Buttons 44 px+, body text 16 px+, high contrast |

---

## 5. Critic pass

Two sceptical judges argue against the plan. Each objection has a fix (changed in the plan) or a recorded weakness.

### 5.1 Commerzbank business judge

| Objection | Honest assessment | Fix or weakness |
|---|---|---|
| "This already exists — Pleo, Agicap, Qonto's agents, even mBank's own 4-week forecast." | True piece by piece (VERIFIED, `00_ANALYSIS.md` 5.6). Capture is commodity, reimbursement is solved for card users, forecasts exist | **Fix:** never pitch capture as the product. Pitch the chain: hidden liabilities -> forecast -> bank action with approval, bank-agnostic on data. Name mBank's forecast ourselves before a judge does. Positioning lines in `01_SOLUTION.md` section 9 |
| "This is not one of our four agents. It is an invoice scanner." | The real danger, and larger with messy data as the headline (team decision, `DECISIONS.md` R-01) | **Weakness accepted, with mitigations:** (1) every messy-data step ends in a number on the cash forecast; (2) the presenter names the liquidity agent at 1:40 as "what the clean data is for" and shows it end to end; (3) the lost-VAT counter is framed as the tax agent's "optimisation opportunity"; (4) plan B order is ready if the feedback session asks for it |
| "Why Poland? We are a German bank." | Commerzbank owns mBank; the event is in Łódź (UNVERIFIED that judges are local). Still, Polish VAT details mean nothing to a German judge | **Fix:** the pizzeria (their data, German setup) is in the demo; tax details are one sentence. Country rules are a table, not the product |
| "Is the tax logic right?" | Encoded rules are verified through secondary sources, not the statute text. Reimbursement treatment has contrary rulings | **Weakness, recorded.** UI says "confirm with your accountant" on every non-trivial hint. We do not file or advise; we flag |
| "A credit line for a 7-day gap of 8,000 PLN? Just send a reminder." | Correct, and a good CFO would say the same | **Fix:** the card lists "send a reminder" as alternative 1 with zero cost, and sizes the line on the stress case (28k). The agent recommends the cheapest sufficient action first |
| "Where do the interest rate and the approval come from?" | Invented price list of the simulated bank | **Weakness, labelled** in the card ("illustrative, not an offer"). Ask the judges which product and pricing they want to see (Q5) |
| "Would an owner trust it?" | Trust comes from evidence and from being wrong visibly | **Fix:** evidence links, confidence, "needs review" state, undo on autonomous actions, audit trail (`/approvals`) |
| "The forecast only worked because you told it about June." | True | **Turned into the message:** the agent asks, the owner knows. Shown openly in the demo |
| "What about fun?" | Finance is not fun; relief is | Cash weather + plain language + an "all clear" state. No gamification |

### 5.2 Red Hat technical judge

| Objection | Honest assessment | Fix or weakness |
|---|---|---|
| "Is this really running on OpenShift AI, or on a laptop calling a cloud API?" | Must be beyond doubt | **Fix:** route URL in the address bar; `/health` shows the in-cluster model endpoint; the RHOAI dashboard with the served model and MLflow traces is open in a second tab. No external LLM key exists in any Secret |
| "Your bank is fake." | The demo bank is our simulator. That is honest and necessary: no Polish bank sandbox is reachable without TPP status | **Weakness, stated.** Mitigation: PSD2-shaped API, real polling connector, plus one real third-party sandbox (Commerzbank or inFakt) on the Sources page |
| "You call external services (mailbox, NBP, inFakt). 'Runs fully on OpenShift'?" | The app, agents and model run on the cluster; data sources are external by nature | Ask early (Q3). If outbound traffic is blocked or frowned upon: in-cluster mail catcher + cached rates; the connector code is unchanged |
| "Where is the agent? This looks like a pipeline with an LLM call." | Fair. Most of the value is deterministic by design | **Fix:** three places with real agent behaviour: (1) chat with tool calling, (2) liquidity agent choosing among actions and running scenario tools, (3) ingestion agent deciding review vs auto-confirm. Tools exposed over MCP. We say openly: "numbers are code, judgement and language are the model" |
| "Too big for the time." | Yes if everything is built. | **Fix:** must-have path is 5 screens and 3 connectors; cut order is written down (`04_DEV_PLAN.md` section 5) |
| "Bonus items?" | Chosen for cost, not for count | See `01_SOLUTION.md` section 7; show each to Georg/Karsten as soon as it works |
| "Single node — will it survive the demo?" | Risk | **Fix:** one model, no llm-d, resource limits on every pod, no notebooks running during the demo, a smoke test script before the pitch |
| "Structured output from a small open model is flaky." | True without constraints | **Fix:** JSON-schema-guided decoding in vLLM for extraction; validation checks; low confidence -> human review |

### 5.3 Weaknesses we accept (say them before the judges do)

1. The bank is simulated; one third-party sandbox proves real connectivity.
2. Tax hints are verified through secondary sources and labelled as hints.
3. Receipt reading accuracy was not measured before the event; unsure fields go to the owner.
4. The forecast is simple on purpose; it needs the owner for one-off events.
5. Credit pricing is illustrative.
