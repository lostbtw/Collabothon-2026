-- Forecast events the owner states ("closed 1-30 June"), from the form or the chat. Role 4's engine reads them;
-- doc has the shape of forecast.schema.json#/properties/events/items.
create table forecast_events (
  id         text primary key,
  company_id text not null references companies(id),
  doc        jsonb not null,
  seq        bigserial not null
);
create index forecast_events_company on forecast_events (company_id, seq);
