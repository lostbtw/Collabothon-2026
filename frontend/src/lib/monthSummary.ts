// A month's figures by category: from the books when the month is booked, otherwise from the bank payments
// (the backend sums them with `basis=bank`), so a month whose matches are not checked yet is not shown as empty.
import { api, type LedgerSummary } from "../api/client";
import { monthRange, previousMonth } from "./costTypes";

export type MonthSummary = { summary: LedgerSummary; fromBank: boolean };

async function one(companyId: string, month: string, basis: "ledger" | "bank"): Promise<LedgerSummary | null> {
  return api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month), basis: basis === "bank" ? "bank" : undefined }).catch(() => null);
}

/** The month and the month before, on the same basis so the two compare. Null when the backend has no summary. */
export async function monthAndBefore(companyId: string, month: string): Promise<[MonthSummary | null, LedgerSummary | null]> {
  // All four at once (books and bank, this month and the one before), then pick: one round trip, not three.
  const [books, bank, booksBefore, bankBefore] = await Promise.all([
    one(companyId, month, "ledger"), one(companyId, month, "bank"),
    one(companyId, previousMonth(month), "ledger"), one(companyId, previousMonth(month), "bank"),
  ]);
  if (!books) return [null, null];
  // The books hold only what was checked. When the bank shows more payments for the month than the books, the
  // month is not booked yet: show it from the bank (and say so).
  const count = (x: LedgerSummary) => x.rows.reduce((n, r) => n + r.entries, 0);
  const fromBank = Boolean(bank && count(bank) > count(books));
  const current: MonthSummary = fromBank ? { summary: { ...bank!, kpis: books.kpis }, fromBank } : { summary: books, fromBank };
  return [current, fromBank ? bankBefore : booksBefore];
}
