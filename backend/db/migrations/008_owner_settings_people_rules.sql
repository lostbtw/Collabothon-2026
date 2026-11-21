alter table people add column pay_type text;
alter table people add column card_last4 text[] not null default '{}';
alter table people add column statement_names text[] not null default '{}';
alter table people add column tax_id text;
alter table people add column iban text;

create table company_settings (
  company_id       text primary key references companies(id),
  vat_period       text not null default 'monthly' check (vat_period in ('monthly', 'quarterly')),
  accountant_email text,
  safety_buffer    numeric(14, 2),
  late_client_days integer not null default 7 check (late_client_days > 0),
  weekly_summary   boolean not null default false
);

create table category_rules (
  id              text primary key,
  company_id      text not null references companies(id),
  raw             text not null,
  counterparty_id text,
  category        text not null,
  learned_at      timestamptz not null default now(),
  unique (company_id, raw)
);
