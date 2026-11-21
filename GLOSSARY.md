# Ordo

Ordo turns a small company's scattered money data into one owner-approved ledger, forecasts cash from it, and prepares the fix when a gap is coming. The owner decides; every action runs only in simulation.

## Companies and people

**Company**:
One business whose finances Ordo runs; the demo has Borsuk Labs (messy data, PLN) and Pizzeria Amalfi (the organisers' data, EUR).
_Avoid_: Tenant, client, account

**Owner**:
The person who runs the Company and makes every Decision.
_Avoid_: User, admin, customer

**Person**:
Someone who belongs to a Company (owner, employee or contractor), identified by e-mail address when forwarding Documents.
_Avoid_: User, sender

**As-of date**:
The day a Company's figures are computed for; Borsuk Labs is seen on 2026-11-21, Pizzeria Amalfi on 2025-05-15.
_Avoid_: Today, now, demo clock

## Incoming data

**Source**:
One place money data is pulled from by a connector, such as the invoices mailbox or one bank account.
_Avoid_: Integration, feed, channel

**RawItem**:
One unit fetched from a Source exactly as received, before any reading or interpretation.
_Avoid_: Upload, file, message

**Document**:
An invoice or receipt read from a RawItem, with its fields and a confidence.
_Avoid_: Bill, scan, receipt (when the kind does not matter)

**Golden record**:
The one Document kept for a purchase that arrived in several copies; the other copies stay as duplicates and evidence.
_Avoid_: Master, canonical document

**Transaction**:
One booked line on a bank account or card.
_Avoid_: Payment, bank line, operation

**Match**:
The link between a Document and the Transaction that paid it, or the finding that no such Transaction exists.
_Avoid_: Reconciliation, pairing

**Paid by**:
Who really paid a purchase: the company, the owner privately, an employee privately, or unknown.
_Avoid_: Payer, funding source

**Recurring series**:
A repeating flow (salaries, rent, a subscription) recognised from history and used both to forecast it and to confirm its Matches automatically.
_Avoid_: Subscription, pattern, schedule

## Books and forecast

**Ledger entry**:
One line in the owner-approved books, created only from a decided Match or Recommendation.
_Avoid_: Booking, journal line, posting

**Forecast**:
The day-by-day cash projection for a Company from its As-of date, made of Forecast components.
_Avoid_: Prediction, projection, cash plan

**Forecast component**:
One named, evidenced part of a Forecast, such as "Salaries, last business day".
_Avoid_: Driver, factor, series

**Forecast event**:
A fact about the future the Owner states, such as "closed 1–30 June", that changes the Forecast.
_Avoid_: Owner event, override, assumption

## Agents and decisions

**Recommendation**:
Something an agent proposes or reports to the Owner, always carrying a control level, an execution mode, an explanation and evidence; "card" is only its look in the UI.
_Avoid_: Card (outside the UI), suggestion, alert, task

**Control level**:
How much the Owner is involved in an agent output: analysed autonomously, recommendation, or approval required.
_Avoid_: Autonomy level, permission

**Execution mode**:
Whether an action runs at all: none, simulated, or permitted; this build only ever runs simulated.
_Avoid_: Dry run, mode

**Decision**:
The Owner's approve, approve-with-changes or reject on a Recommendation or Match.
_Avoid_: Approval (for the act), confirmation

**Approval**:
The audit record of one Decision, including rejections, with who decided, when, what changed and the simulated result.
_Avoid_: Sign-off, consent

**Simulated execution**:
Carrying out an approved action against the Sandbox Bank instead of a real bank. The app says once, in the sidebar, that every action is simulated.
_Avoid_: Mock execution, test payment

**Sandbox Bank**:
The team's own PSD2-shaped bank simulator: the demo's bank and the target of every Simulated execution.
_Avoid_: Fake bank, mock bank

**Demo-day rate**:
The fixed exchange rate the demo story uses for converting balances: 4.41 PLN per EUR and 4.0613 PLN per USD.
_Avoid_: Spot, today's rate

## Building in parallel

**Stand-in**:
The contract fixture or local substitute a role builds against until another role's real piece lands.
_Avoid_: Mock (in planning), stub, placeholder
