-- The chat's SQL tool reads only these views, as role ordo_readonly, each filtered to ordo.company_id.
create view v_ledger as
  select id, doc->>'date' as date, doc->>'type' as type, doc->>'category' as category,
         (doc->'amount_base'->>'amount')::numeric as amount_base, doc->'amount_base'->>'currency' as currency,
         doc->>'paid_by' as paid_by, doc->>'status' as status, doc->>'counterparty_id' as counterparty_id,
         doc->>'document_id' as document_id, doc->>'explanation' as explanation
  from ledger_entries where company_id = current_setting('ordo.company_id', true);

create view v_transactions as
  select id, doc->>'account_id' as account_id, doc->>'booking_date' as booking_date,
         (doc->'amount_base'->>'amount')::numeric as amount_base, doc->'amount_base'->>'currency' as currency,
         doc->>'counterparty_name_raw' as counterparty, doc->>'description' as description,
         doc->>'category' as category, doc->>'match_status' as match_status
  from transactions where company_id = current_setting('ordo.company_id', true);

create view v_documents as
  select id, doc->>'doc_type' as doc_type, doc->>'direction' as direction, doc->>'number' as number,
         doc->>'issue_date' as issue_date, doc->>'due_date' as due_date, doc->'seller'->>'name' as seller,
         (doc->'totals'->'gross_base'->>'amount')::numeric as gross_base, doc->'totals'->'gross_base'->>'currency' as currency,
         doc->>'status' as status
  from documents where company_id = current_setting('ordo.company_id', true);

create view v_accounts as
  select id, doc->>'name' as name, doc->>'kind' as kind, doc->>'currency' as currency,
         (doc->'balance'->>'amount')::numeric as balance, (doc->>'include_in_liquidity')::boolean as include_in_liquidity
  from accounts where company_id = current_setting('ordo.company_id', true);

create view v_recommendations as
  select id, doc->>'agent' as agent, doc->>'type' as type, doc->>'title' as title, doc->>'status' as status,
         doc->>'control_level' as control_level, doc->>'execution_mode' as execution_mode, doc->>'created_at' as created_at
  from recommendations where company_id = current_setting('ordo.company_id', true);

create view v_forecast_components as
  select f.id as forecast_id, c->>'id' as component_id, c->>'label' as label, c->>'kind' as kind,
         (c->'amount_base'->>'amount')::numeric as amount_base, c->'amount_base'->>'currency' as currency,
         c->'dates'->>0 as date, (c->>'confidence')::numeric as confidence
  from forecasts f, jsonb_array_elements(f.doc->'components') c
  where f.company_id = current_setting('ordo.company_id', true)
    and f.scenario_of is null
    and f.seq = (select max(seq) from forecasts g where g.company_id = f.company_id and g.scenario_of is null);

-- Creating a role needs CREATEROLE; where the app user lacks it, the DBA runs this block once.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ordo_readonly') then
    create role ordo_readonly nologin;
  end if;
  execute 'grant ordo_readonly to ' || quote_ident(current_user);
exception when insufficient_privilege then
  raise notice 'ordo_readonly not created (no CREATEROLE); the SQL tool stays off until a DBA creates it';
end $$;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'ordo_readonly') then
    execute 'grant usage on schema public to ordo_readonly';
    execute 'grant select on v_ledger, v_transactions, v_documents, v_accounts, v_recommendations, v_forecast_components to ordo_readonly';
  end if;
end $$;

create table chat_messages (
  session_id text not null,
  company_id text not null,
  seq        bigserial,
  role       text not null check (role in ('user', 'assistant')),
  content    text not null,
  at         timestamptz not null default now(),
  primary key (session_id, seq)
);
