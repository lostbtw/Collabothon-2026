-- What the owner tells Ordo in Settings (role 6's screens; endpoints in backend/api/routes/owner.py).

-- People: how each one is paid and how they show up on bank lines, so a payment can be tied to a person.
alter table people add column pay_type text;
alter table people add column card_last4 text[] not null default '{}';
alter table people add column statement_names text[] not null default '{}';
alter table people add column tax_id text;
alter table people add column iban text;

-- Company settings and alerts. One row per company; a missing row means the defaults in owner.py.
create table company_settings (
  company_id       text primary key references companies(id),
  vat_period       text not null default 'monthly' check (vat_period in ('monthly', 'quarterly')),
  accountant_email text,
  safety_buffer    numeric(14, 2),
  late_client_days integer not null default 7 check (late_client_days > 0),
  weekly_summary   boolean not null default false
);

-- Rules the owner taught by changing a payment's type: this spelling on a bank line or invoice is this
-- counterparty, of this category. The counterparty's default_category carries the rule into the pipeline
-- (categorise() reads it first, as "history"); this table is the list the owner sees and can delete from.
create table category_rules (
  id              text primary key,
  company_id      text not null references companies(id),
  raw             text not null,
  counterparty_id text,
  category        text not null,
  learned_at      timestamptz not null default now(),
  unique (company_id, raw)
);
