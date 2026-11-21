-- "Latest" means last written: fixtures are dated on the companies' as-of dates, new rows on the real clock.
alter table sync_runs       add column seq bigserial;
alter table forecasts       add column seq bigserial;
alter table recommendations add column seq bigserial;
alter table approvals       add column seq bigserial;
