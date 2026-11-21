// A month's figures by category: from the books when the month is booked, otherwise from the bank payments (`basis=bank`).
import { api, type LedgerSummary } from "../api/client";
import { monthRange, previousMonth } from "./costTypes";

export type MonthSummary = { summary: LedgerSummary; fromBank: boolean };

async function one(companyId: string, month: string, basis: "ledger" | "bank"): Promise<LedgerSummary | null> {
  return api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month), basis: basis === "bank" ? "bank" : undefined }).catch(() => null);
}

export async function monthAndBefore(companyId: string, month: string): Promise<[MonthSummary | null, LedgerSummary | null]> {
  const [books, bank, booksBefore, bankBefore] = await Promise.all([
    one(companyId, month, "ledger"), one(companyId, month, "bank"),
    one(companyId, previousMonth(month), "ledger"), one(companyId, previousMonth(month), "bank"),
  ]);
  if (!books) return [null, null];
  const count = (x: LedgerSummary) => x.rows.reduce((n, r) => n + r.entries, 0);
  const fromBank = Boolean(bank && count(bank) > count(books));
  const current: MonthSummary = fromBank ? { summary: { ...bank!, kpis: books.kpis }, fromBank } : { summary: books, fromBank };
  return [current, fromBank ? bankBefore : booksBefore];
}
