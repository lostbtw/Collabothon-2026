-- Ordo database, first cut.
--
-- Every contract entity is stored whole in `doc` (jsonb, exactly the shape of contracts/schemas/<entity>.schema.json),
-- so a schema change in contracts/ needs no migration. The other columns are generated from `doc` and exist only
-- to filter and to enforce the idempotency keys of contracts/events.md. `company_id` is a plain column because
-- some entities (match, approval, transaction, raw item, sync run) do not carry it in their JSON.

create table companies (
  id            text primary key,
  name          text not null,
  base_currency text not null,
  country       text not null,
  as_of_date    date not null
);

create table people (
  id         text primary key,
  company_id text not null references companies(id),
  name       text not null,
  email      text not null unique,
  role       text not null check (role in ('owner', 'employee', 'contractor'))
);

-- Extra addresses a Person sends from (the real phone used in the live demo). Filled only from a Secret at seed time.
create table person_addresses (
  address   text primary key,
  person_id text not null references people(id)
);

create table sources (
  id         text primary key,
  company_id text,
  doc        jsonb not null,
  connector  text generated always as (doc->>'connector') stored
);

create table sync_runs (
  id         text primary key,
  company_id text,
  doc        jsonb not null,
  source_id  text generated always as (doc->>'source_id') stored,
  started_at text generated always as (doc->>'started_at') stored
);
create index sync_runs_source on sync_runs (source_id, started_at desc);

create table raw_items (
  id                text primary key,
  company_id        text,
  doc               jsonb not null,
  source_id         text generated always as (doc->>'source_id') stored,
  idempotency_key   text generated always as (doc->>'idempotency_key') stored,
  processing_status text generated always as (doc->>'processing_status') stored
);
create unique index raw_items_idempotency_key on raw_items (idempotency_key);

create table documents (
  id                text primary key,
  company_id        text,
  doc               jsonb not null,
  first_raw_item_id text generated always as (doc->'raw_item_ids'->>0) stored,
  status            text generated always as (doc->>'status') stored,
  direction         text generated always as (doc->>'direction') stored
);
create unique index documents_first_raw_item on documents (first_raw_item_id);

create table accounts (
  id         text primary key,
  company_id text,
  doc        jsonb not null
);

create table transactions (
  id           text primary key,
  company_id   text,
  doc          jsonb not null,
  account_id   text generated always as (doc->>'account_id') stored,
  external_id  text generated always as (doc->>'external_id') stored,
  booking_date text generated always as (doc->>'booking_date') stored,
  match_status text generated always as (doc->>'match_status') stored
);
create unique index transactions_account_external on transactions (account_id, external_id);

create table counterparties (
  id         text primary key,
  company_id text,
  doc        jsonb not null
);

create table matches (
  id          text primary key,
  company_id  text,
  doc         jsonb not null,
  document_id text generated always as (doc->>'document_id') stored,
  match_type  text generated always as (doc->>'match_type') stored,
  status      text generated always as (doc->>'status') stored
);
create unique index matches_open_per_document on matches (document_id, match_type) where status = 'suggested';

create table ledger_entries (
  id          text primary key,
  company_id  text,
  doc         jsonb not null,
  match_id    text generated always as (doc->>'match_id') stored,
  type        text generated always as (doc->>'type') stored,
  status      text generated always as (doc->>'status') stored,
  date        text generated always as (doc->>'date') stored,
  approval_id text generated always as (doc->>'approval_id') stored
);
create unique index ledger_entries_per_match on ledger_entries (match_id, type) where match_id is not null;

create table forecasts (
  id           text primary key,
  company_id   text,
  doc          jsonb not null,
  generated_at text generated always as (doc->>'generated_at') stored,
  inputs_hash  text generated always as (doc->>'inputs_hash') stored,
  scenario_of  text generated always as (doc->>'scenario_of') stored
);
create unique index forecasts_base_inputs on forecasts (company_id, inputs_hash)
  where scenario_of is null and inputs_hash is not null;
create index forecasts_latest on forecasts (company_id, generated_at desc);

create table recommendations (
  id            text primary key,
  company_id    text,
  doc           jsonb not null,
  agent         text generated always as (doc->>'agent') stored,
  type          text generated always as (doc->>'type') stored,
  status        text generated always as (doc->>'status') stored,
  control_level text generated always as (doc->>'control_level') stored,
  subject_id    text generated always as (doc->'subject'->>'id') stored,
  created_at    text generated always as (doc->>'created_at') stored
);
create unique index recommendations_open_per_subject on recommendations (type, subject_id)
  where status in ('new', 'seen') and subject_id is not null;

create table approvals (
  id           text primary key,
  company_id   text,
  doc          jsonb not null,
  subject_type text generated always as (doc->>'subject_type') stored,
  subject_id   text generated always as (doc->>'subject_id') stored,
  decided_at   text generated always as (doc->>'decided_at') stored
);

-- Queue (contracts/events.md): one outbox table, one delivery row per (event, consumer), LISTEN/NOTIFY.
create table outbox (
  id             text primary key,
  type           text not null,
  company_id     text not null,
  correlation_id text,
  causation_id   text,
  producer       text not null,
  payload        jsonb not null,
  occurred_at    timestamptz not null default now(),
  seq            bigserial not null unique
);

create table outbox_delivery (
  event_id     text references outbox(id) on delete cascade,
  consumer     text not null,
  status       text not null default 'pending' check (status in ('pending', 'done', 'dead')),
  attempts     int  not null default 0,
  locked_until timestamptz,
  primary key (event_id, consumer)
);
create index outbox_delivery_pending on outbox_delivery (consumer, status) where status = 'pending';

-- Which consumer group receives which event type (from the table in contracts/events.md). Reference data.
create table outbox_subscription (
  consumer   text not null,
  event_type text not null,
  primary key (consumer, event_type)
);
insert into outbox_subscription (consumer, event_type) values
  ('extractor',  'raw_item.received'),
  ('normaliser', 'raw_item.received'),
  ('matcher',    'document.extracted'),
  ('matcher',    'transaction.ingested'),
  ('matcher',    'match.decided'),
  ('finance',    'transaction.ingested'),
  ('finance',    'match.decided'),
  ('finance',    'ledger.entry.approved'),
  ('finance',    'approval.recorded'),
  ('finance',    'execution.simulated'),
  ('agents',     'match.suggested'),
  ('agents',     'forecast.updated');

create function outbox_fan_out() returns trigger language plpgsql as $$
begin
  insert into outbox_delivery (event_id, consumer)
    select new.id, s.consumer from outbox_subscription s where s.event_type = new.type;
  -- every event also goes to the browser (SSE)
  insert into outbox_delivery (event_id, consumer) values (new.id, 'sse');
  perform pg_notify('outbox', new.id);
  return new;
end $$;

create trigger outbox_fan_out after insert on outbox for each row execute function outbox_fan_out();
