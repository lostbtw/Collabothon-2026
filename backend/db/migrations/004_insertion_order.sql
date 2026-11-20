-- "Latest" means last written, not the newest timestamp in the JSON: fixtures and the demo story are dated on the
-- companies' as-of dates while new rows carry the real clock. Updates (put) keep a row's position.
alter table sync_runs       add column seq bigserial;
alter table forecasts       add column seq bigserial;
alter table recommendations add column seq bigserial;
alter table approvals       add column seq bigserial;
