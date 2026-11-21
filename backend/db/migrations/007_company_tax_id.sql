-- A document whose buyer tax id is the company's own keeps its VAT deductible; otherwise PL-VAT-01.
alter table companies add column tax_id text;
