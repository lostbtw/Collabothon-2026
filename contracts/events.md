# Events and queue messages

**Transport (decision D-07):** one Postgres table `outbox` + `LISTEN/NOTIFY`. No Kafka, no Redis.
Workers claim rows with `SELECT ... FOR UPDATE SKIP LOCKED`. The API relays the same events to the browser over SSE (`GET /api/v1/events/stream`).

**Envelope:** `schemas/event.schema.json`. Examples: `fixtures/event.json` (the full "live receipt" chain).

```json
{"id":"evt_9002","type":"document.extracted","occurred_at":"2026-11-21T10:14:52Z","company_id":"co_borsuk",
 "correlation_id":"raw_mail412","causation_id":"evt_9001","producer":"extractor",
 "payload":{"document_id":"doc_rcpt412","status":"needs_review"}}
```

Rules:
1. Payloads are **small**: ids plus a few summary fields for the UI toast. Consumers fetch the full entity over REST.
2. `correlation_id` = id of the first RawItem. Everything that one receipt/bank line causes carries it. The UI uses it to animate one item through the pipeline.
3. Handlers are **idempotent**: processing the same event twice must not create a second Document/Match/LedgerEntry (unique keys below).
4. Delivery is at-least-once. A row is deleted (or marked `done`) only after the handler commits.
5. A handler that fails 3 times marks the row `dead` and sets `raw_item.processing_status = failed`. The Sources page shows the count.

## Event types

| Type | Producer | Payload fields | Consumers | Idempotency key of the consumer's write |
|---|---|---|---|---|
| `sync.run.started` | connector | `sync_run_id, source_id` | UI (spinner on source) | - |
| `sync.run.finished` | connector | `sync_run_id, source_id, status, items_new, error?` | UI ("last synced 12 s ago") | - |
| `raw_item.received` | connector | `raw_item_id, kind, source_id` | extractor (files), normaliser (bank lines, API invoices) | `raw_item.idempotency_key` (unique index) |
| `document.extracted` | extractor | `document_id, status, gross, seller, flags[]` | matcher, UI | `document.raw_item_ids[0]` unique |
| `document.duplicate_detected` | matcher | `document_id, duplicate_of, reason` | UI | (`document_id`) |
| `transaction.ingested` | normaliser | `transaction_id, account_id, amount, booking_date` | matcher, finance engine | (`account_id`, `external_id`) unique |
| `match.suggested` | matcher | `match_id, document_id, transaction_id?, paid_by, score` | agent service (creates Recommendation), UI | (`document_id`, `match_type`) for open matches |
| `match.decided` | API (also when the owner decides a Recommendation whose subject is a Match: one tap decides both) | `match_id, status, approval_id` | finance engine (books the ledger entries, already approved), matcher (learn alias) | `approval_id` |
| `ledger.entry.proposed` | finance engine | `ledger_entry_id, type, amount` | UI | (`match_id`, `type`). Not used in the demo flow: entries from a decided Match are booked approved directly (D-20) |
| `ledger.entry.approved` | API / finance engine | `ledger_entry_id, approval_id` | finance engine (forecast) | `approval_id` |
| `forecast.updated` | finance engine | `forecast_id, min_balance, min_balance_previous, first_negative_date` | agent service (liquidity agent), UI chart | `forecast.inputs_hash` (skip if unchanged) |
| `recommendation.created` | agent service | `recommendation_id, type, control_level` | UI inbox badge | (`type`, `subject.id`) for open recommendations |
| `recommendation.status_changed` | API | `recommendation_id, status` | UI | - |
| `approval.recorded` | API | `approval_id, subject_type, subject_id, decision` | UI, finance engine | `approval_id`. The executor is **not** a consumer: the decision endpoint calls it in-process and returns the reference in the same response (D-19) |
| `execution.simulated` | executor | `approval_id, reference, result` | finance engine (scenario becomes base), UI | `approval_id` |

## The live-demo chain (target: under 30 s end to end)

```
mail connector poll (every 20 s)            raw_item.received      t+0..20 s
extractor: vision model -> Document          document.extracted     +5..10 s
matcher: dedup, match, who paid              match.suggested        +1 s
agent service: reimbursement card            recommendation.created +1 s (template text, no LLM wait)
finance engine: forecast recompute           forecast.updated       +1 s
UI: toast -> inbox card -> chart moves       (SSE)                  immediate
```

Debounce: the finance engine recomputes at most once per 2 s per company.

## Queue table (reference DDL)

```sql
create table outbox (
  id            text primary key,          -- evt_...
  type          text not null,
  company_id    text not null,
  correlation_id text,
  causation_id  text,
  producer      text not null,
  payload       jsonb not null,
  occurred_at   timestamptz not null default now(),
  -- one row per (event, consumer group) is created by a trigger into outbox_delivery:
  unique (id)
);
create table outbox_delivery (
  event_id   text references outbox(id),
  consumer   text not null,                -- 'extractor' | 'matcher' | 'finance' | 'agents' | 'executor' | 'sse'
  status     text not null default 'pending',   -- pending | done | dead
  attempts   int  not null default 0,
  locked_until timestamptz,
  primary key (event_id, consumer)
);
```
