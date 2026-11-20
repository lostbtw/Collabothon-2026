# 03 — FX Shield (the FX hedging agent)

Self-contained. Owner: role 4 (engine and cards), with small parts for roles 2 and 6.
Source: a team member's brief "FX Shield for small businesses" (20 Nov 2026), merged into the Ordo plan. It replaces the earlier, vaguer "FX exposure list" item.
Claim labels: `VERIFIED (source)` / `UNVERIFIED (reason)`.

Pitch line: **"We don't guess the exchange rate. We show what you could lose if it goes against you, and what it costs to protect your most important deals."**

---

## 1. Problem and idea

Small businesses rarely hedge currency risk. Hedging small amounts is not worth the cost, and owners have no treasury knowledge. But now and then a business gets an unusually large foreign-currency invoice. One bad exchange-rate move on that invoice can wipe out most of the profit on the deal, and nobody notices until payment day.

FX Shield watches incoming and outgoing foreign-currency invoices and protects **only the deals where currency risk really matters**.

| Principle | Meaning |
|---|---|
| A hedge is insurance, not a bet | We never claim to know where the rate will go |
| Measure the downside, not the average | On average the rate moves both ways and the average result is about zero. We measure what happens in the bad cases |
| Speak in profit, not in percent | "This order earns you 8,000 PLN. In a bad case the exchange rate eats 6,600 PLN of it." |
| Say "not worth it" out loud | Most invoices should **not** be hedged. Saying so builds trust |
| The owner decides | Approve / Change / Reject. Execution is simulated |

## 2. How it fits Ordo

| FX Shield needs | Ordo already has it |
|---|---|
| Foreign-currency invoices with amount, currency, due date | The ingestion pipeline: e-invoice XML, PDF or photo read by the model on the cluster (roles 1 and 3) |
| Exchange-rate history | The NBP connector (role 2) |
| **When** the money will really move | Per-client average payment delay from the ledger (role 4). A client who pays 23 days late gets a hedge dated 23 days after the due date |
| Natural offsets in the same currency | Bank balances and open payables per currency (roles 2 and 4) |
| A card with explanation, evidence, approval, simulated execution | The Recommendation / Approval contracts and the inbox (roles 5 and 6) |

It is the challenge's use case 2: "FX hedging agent: identifies currency risks from foreign invoices and structures hedges using Commerzbank products". The liquidity agent stays the complete end-to-end use case; FX Shield is the second agent.

## 3. Core logic

| # | Step | Detail |
|---|---|---|
| 1 | **Detect** | A document in a currency other than the company's base currency is approved or auto-confirmed. Take amount `N`, currency, direction (receivable = we will receive foreign currency; payable = we will pay it), and the expected cash date = due date + that counterparty's average payment delay |
| 2 | **Net out free protection** | Net exposure per currency and time window (±15 days) = receivables − payables − balance already held in that currency. If the net is near zero, stop: "already covered by your own EUR costs" (natural hedge) |
| 3 | **Scenarios, no prediction** | Horizon `h` = days until the expected cash date. From 3 years of daily NBP rates take every historical change over `h` days: `r = S(t+h) / S(t) − 1`. Apply each `r` to today's rate. About 700 scenarios |
| 4 | **Measure the downside** | Loss per scenario = `N × S_today × max(0, −r)` for a receivable, `max(0, +r)` for a payable. Report: bad case = 95th percentile loss; **expected shortfall** = average loss across the worst 10% of scenarios |
| 5 | **Frame it as margin** | Compare the expected shortfall with the profit on the deal (section 5 says where the profit figure comes from) |
| 6 | **Decide** | Propose a hedge only if (a) the expected shortfall is at least 25% of the deal's profit, or above the owner's loss limit (default 2,000 PLN), **and** (b) the hedge costs clearly less than the shortfall it removes. Otherwise create an information card: "Hedging is not worth it here", with the numbers |
| 7 | **Structure** | From the product catalog (section 6): free options first, then a forward, then an option. Choose hedge ratio, date and indicative rate |
| 8 | **Explain and ask** | Plain-language card: without hedge vs with hedge, side by side. Buttons: Approve / Change / Reject |
| 9 | **Simulate and log** | Simulated order at the sandbox bank; Approval record with the data used, the rule applied and who approved |

Thresholds in step 6 (25%, 2,000 PLN, 10%, 95%) are settings, not constants.

## 4. Verified on real data

Spike `spikes/05_fx_downside/fx_downside.py`, run 20 Nov 2026 against the NBP API: 756 daily rates per currency (21 Nov 2023 – 20 Nov 2026), 7–14 s to download three currencies. VERIFIED (spike 05, output in the same folder).

Rate changes over 45 days, last 3 years:

| Currency vs PLN | 5th percentile | Median | 95th percentile | Mean |
|---|---|---|---|---|
| EUR | −1.62% | −0.04% | +1.85% | +0.08% |
| USD | −3.92% | −0.23% | +4.76% | +0.01% |
| CHF | −3.07% | +0.10% | +3.68% | +0.20% |

Four invoices through the rule (forward cost assumed 0.3% of the amount — illustrative):

| Invoice | Worth today | Average result | Bad case (95th pct) | Expected shortfall | Deal profit | Shortfall / profit | Forward cost | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1,150 USD software bill, 30 days | 4,670 PLN | −1 PLN | 179 PLN | 187 PLN | — (limit 2,000) | — | 14 PLN | **Not worth it** |
| 18,400 EUR sales invoice, 45 days | 81,989 PLN | +63 PLN | 1,330 PLN | 1,426 PLN | 14,000 PLN | 10% | 246 PLN | **Not worth it** |
| **40,000 USD one-off order, 45 days** | 162,452 PLN | +19 PLN | 6,374 PLN | **6,595 PLN** | **8,000 PLN** | **82%** | 487 PLN | **Propose forward** |
| 42,000 USD equipment purchase, 60 days | 170,575 PLN | +47 PLN | 8,895 PLN | 9,425 PLN | 12,000 PLN | 79% | 512 PLN | **Propose forward** |

What the data shows:

1. The "average" column is near zero every time. The brief is right: the average hides the risk.
2. EUR/PLN is calm. Ordinary EUR invoices do not need hedging — a real, defensible "not worth it".
3. USD/PLN moves about 2.5 times more. One large USD deal with a thin margin is exactly the case the brief describes, and the third row reproduces its example almost to the number ("earns 8,000, a bad case eats 6,500").

## 5. Where the deal's profit comes from

An invoice does not say how much profit it carries. Order of preference:

| Source | When | Shown as |
|---|---|---|
| Owner types it on the card ("Change" -> "profit on this deal") | Any time | "your figure" |
| Company's average margin from the approved ledger × invoice value | Default | "estimated from your average margin of X%" |
| Owner's absolute loss limit per deal (default 2,000 PLN) | No ledger yet, or a purchase without a linked sale | "above your limit of 2,000 PLN" |

The demo uses the first: the scenario sets a profit of 8,000 PLN for the hero order.

## 6. Product catalog (simplified, illustrative)

| Order | Product | What the owner gets | Cost in the demo | Upside kept? | Action in this build |
|---|---|---|---|---|---|
| 1 | **Natural hedge** | Use foreign currency you already have or will receive to pay foreign bills | 0 | yes | Recommendation only |
| 2 | **Forward** (fix the rate today for a set date) | Certainty: the PLN amount is locked | 0.3% of the amount (bank margin) | no | Approval required; simulated order |
| 3 | **Option** (the right, not the duty, to exchange at a set rate) | Protection against the bad case, keeps the good case | 1.2% of the amount (premium) | yes | Shown as the alternative; not executable in this build |

Bank names for the card: Commerzbank offers FX trading for business clients through "FX Live Trader" — VERIFIED ([page](https://www.commerzbank.de/unternehmerkunden/zahlungsverkehr/devisenhandel/)); mBank offers spot and forward on "mPlatforma walutowa" — VERIFIED via search snippet only. Minimum deal sizes, real margins and premiums: UNVERIFIED — the 0.3% and 1.2% are placeholders and labelled "illustrative, not an offer". Real forward pricing also includes the interest-rate difference between the two currencies; this build ignores it and says so.

Hedge ratio and date:

| Situation | Ratio | Date |
|---|---|---|
| Payable with a fixed due date | 100% | Due date |
| Receivable from a client who pays on time | 100% | Due date |
| Receivable from a client with a history of late payment | 80% | Due date + that client's average delay; card says why |

## 7. What the owner sees

Hero card (type `fx_hedge`, control level `approval_required`, execution `simulated`). Full example: `contracts/fixtures/recommendation.json`, id `rec_fx01`.

> **Protect the profit on the Lakeshore order**
> This 40,000 USD order earns you about 8,000 PLN. You will be paid in 45 days. If the dollar falls the way it did in the worst tenth of the last three years, you lose about 6,600 PLN of that profit. Fixing the rate today costs about 490 PLN.

| | Without hedge | With forward |
|---|---|---|
| Bad case | −6,595 PLN | −487 PLN (the cost) |
| Good case | +7,733 PLN | −487 PLN (you give up the gain) |
| What you know today | Nothing | Exactly what you will receive |

Why? panel: 724 historical scenarios, link to the rate history, the invoice, the rule ("shortfall 82% of profit, above the 25% threshold; cost 7% of the shortfall"), alternatives (do nothing; option at about 1,950 PLN keeps the upside).

"Not worth it" card (type `info`, control level `recommendation`), id `rec_fx02`:

> **No need to hedge the Nordwind invoice**
> 18,400 EUR, due in 45 days. Even in a bad case the exchange rate costs about 1,400 PLN, 10% of the profit on this job. Hedging would not pay off.

Control model:

| Step | Level | Execution |
|---|---|---|
| Detect, net, run scenarios, compute downside | analysed autonomously | none |
| "Not worth hedging" | recommendation | none |
| "Use your EUR balance to pay this EUR bill" (natural hedge) | recommendation | none |
| "Fix the rate with a forward" | approval required | simulated order at the sandbox bank |

Effect on the liquidity forecast: after approval, the forecast component for that invoice switches from "at today's rate, uncertain" to the locked PLN amount, and its low/high band closes.

## 8. Contracts

No schema change is needed.

| Thing | Where |
|---|---|
| Card | `Recommendation` with `agent: "fx"`, `type: "fx_hedge"` or `"info"`; numbers in `explanation.calculation[]`; option and "do nothing" in `explanation.alternatives[]` |
| Action | `proposed_action.kind: "book_fx_forward"`, params `{sell_currency, buy_currency, notional, rate, value_date, hedge_ratio}` |
| Execution target | `POST /v1/fx-forwards` on the Sandbox Bank (`contracts/bank-sim-api.md`) -> `{reference: "SIM-FX-…", status: "booked"}` |
| Exposure list for the dashboard and the chat tool | `GET /api/v1/fx/exposure` (`contracts/openapi.yaml`) |
| Rate history | NBP connector keeps 3 years of table-A rates; refreshed daily |
| Fixtures | `rec_fx01` (propose forward), `rec_fx02` (not worth it) |

## 9. Work, owners, hours

| Task | Role | Hours | Priority |
|---|---|---|---|
| 4.9 FX Shield engine: history scenarios, downside (95th pct, expected shortfall), netting, profit framing, decision rule, product catalog, both cards as Recommendation objects (template text, no LLM needed) | 4 | 5 | **Must** |
| 2.6 NBP connector also stores 3 years of history (extra) | 2 | +0.5 | Must |
| 2.13 Simulated executor also books a forward (extra) | 2 | +0.5 | Must |
| Scenario: one 40,000 USD sales invoice to "Lakeshore Robotics Inc. (SAMPLE)", profit 8,000 PLN, due in 45 days (part of 4.1) | 4 | included | Must |
| FX card uses the existing recommendation card and Why panel: no new component | 6 | 0 | — |
| 6.13 Small with/without-hedge comparison graphic inside the FX card | 6 | 1 | Nice |
| `get_fx_exposure` as a sixth chat tool | 5 | 0.5 | Nice |

Capacity effect (from `python3 tools/status.py forecast`): role 4 goes from 16.5 to 21.5 must-have hours of about 22 available. Its slack is gone. **Consequence: the tax calendar and tax-reserve card (4.6, should-have) will probably not be built.** The "VAT lost this year" figure (4.6a) stays.

If time runs out, FX Shield degrades in this order: drop netting (step 2) -> drop the option alternative -> show only the hero card from the fixture numbers computed by the engine. The scenario method (steps 3–6) is the part to keep: it is about 60 lines, already written in spike 05.

## 10. Demo segment (about 25 seconds)

| Screen | Presenter says |
|---|---|
| Inbox: card "Protect the profit on the Lakeshore order". Open Why? | "A second agent watches foreign invoices. It does not guess the exchange rate. It looks at how the dollar really moved over the last three years: in a bad case, 6,600 of the 8,000 złoty this order earns are gone. Fixing the rate costs 490." |
| Next card: "No need to hedge the Nordwind invoice" | "And for the ordinary euro invoice it says: not worth it. It protects only the deals that matter." |
| Approve the forward -> "SIMULATED — SIM-FX-2026-0003" | "The owner approves. Simulated." |

Where it goes in the 3-minute script is decided when the team prepares the presentation.

## 11. Limits (say them first)

1. History is not a forecast. A move larger than anything in the last three years is possible.
2. The 45-day windows overlap, so the 724 scenarios are not independent. The percentiles are indicative.
3. Forward and option prices are placeholders. A real quote comes from the bank.
4. The deal's profit is an estimate unless the owner enters it.
5. This is decision support, not investment advice. The owner decides.

## 12. Questions for the organisers

See Q18–Q20 in `06_RISKS_AND_QUESTIONS.md`: which Commerzbank or mBank FX products are open to small businesses and from what deal size; whether illustrative forward pricing may be shown; whether the bank would rather see a forward or an option as the default proposal.
