// A month's figures by category: from the books when the month is booked, otherwise from the bank lines
// (the backend sums them with `basis=bank`), so a month whose matches are not checked yet is not shown as empty.
import { api, type LedgerSummary } from "../api/client";
import { monthRange, previousMonth } from "./costTypes";

export type MonthSummary = { summary: LedgerSummary; fromBank: boolean };

async function one(companyId: string, month: string, basis: "ledger" | "bank"): Promise<LedgerSummary | null> {
  return api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month), basis: basis === "bank" ? "bank" : undefined }).catch(() => null);
}

/** The month and the month before, on the same basis so the two compare. Null when the backend has no summary. */
export async function monthAndBefore(companyId: string, month: string): Promise<[MonthSummary | null, LedgerSummary | null]> {
  const books = await one(companyId, month, "ledger");
  if (!books) return [null, null];
  let current: MonthSummary = { summary: books, fromBank: false };
  if (books.rows.length === 0) {
    const bank = await one(companyId, month, "bank");
    if (bank && bank.rows.length > 0) current = { summary: { ...bank, kpis: books.kpis }, fromBank: true };
  }
  const before = await one(companyId, previousMonth(month), current.fromBank ? "bank" : "ledger");
  return [current, before];
}
