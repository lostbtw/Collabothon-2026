create table forecast_events (
  id         text primary key,
  company_id text not null references companies(id),
  doc        jsonb not null,
  seq        bigserial not null
);
create index forecast_events_company on forecast_events (company_id, seq);
