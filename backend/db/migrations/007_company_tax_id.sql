-- The company's own tax id (bare NIP, no PL prefix), for who-paid: a document whose buyer tax id is the company's
-- keeps its VAT deductible; otherwise PL-VAT-01. Null where the company has none in the demo (co_amalfi).
alter table companies add column tax_id text;
