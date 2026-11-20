// Document view logic with no React in it, so it can be tested directly.
import type { DocumentPatch } from "../../api/client";
import type { Match, OrdoDocument } from "../../api/types.gen";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { parseAmount } from "../inbox/model";

/** Below this the field is highlighted and the owner is asked to check it. */
export const LOW_CONFIDENCE = 0.92;

export const firstName = (name?: string | null): string => (name ?? "").split(" ")[0] || "an employee";
export const words = (s: string): string => s.replaceAll("_", " ");

export type FieldKey = "gross" | "vat" | "issue_date" | "seller_tax_id" | "buyer_tax_id";
export type Field = { key: FieldKey; label: string; value: string; input: string; low: boolean; missing?: boolean };

/** The fields the owner sees and may correct. `input` is what the edit box starts with. */
export function fields(d: OrdoDocument): Field[] {
  const conf = d.extraction.field_confidence ?? {};
  const low = (k: string) => typeof conf[k] === "number" && conf[k] < LOW_CONFIDENCE;
  const plain = (m: { amount: string; currency: string }) => formatMoney(m).replace(` ${m.currency}`, "");
  return [
    { key: "gross", label: `Total (${d.totals.gross.currency})`, value: formatMoney(d.totals.gross), input: plain(d.totals.gross), low: low("gross") },
    { key: "vat", label: `VAT (${d.totals.gross.currency})`, value: d.totals.vat ? formatMoney(d.totals.vat) : "Not found", input: d.totals.vat ? plain(d.totals.vat) : "", low: low("vat"), missing: !d.totals.vat },
    { key: "issue_date", label: "Date", value: d.issue_date ? shortDate(d.issue_date) : "Not found", input: d.issue_date ?? "", low: low("issue_date"), missing: !d.issue_date },
    { key: "seller_tax_id", label: "Seller tax number", value: d.seller.tax_id ?? "Not found", input: d.seller.tax_id ?? "", low: low("seller_tax_id"), missing: !d.seller.tax_id },
    { key: "buyer_tax_id", label: "Your tax number on it", value: d.buyer.tax_id ?? "Not found", input: d.buyer.tax_id ?? "", low: low("buyer_tax_id"), missing: !d.buyer.tax_id },
  ];
}

/**
 * The PATCH body: only the blocks that changed (a block such as `buyer` is sent whole). Returns an error text instead when an entry is not valid.
 * Amounts stay decimal strings (parseAmount), never floating point.
 */
export function buildPatch(d: OrdoDocument, edits: Record<FieldKey, string>): { patch: DocumentPatch | null; error: string | null } {
  const patch: DocumentPatch = {};
  for (const f of fields(d)) {
    const typed = edits[f.key].trim();
    if (typed === f.input) continue;
    if (f.key === "gross" || f.key === "vat") {
      // VAT may be zero; a total may not.
      const amount = f.key === "vat" && /^0+([.,]0{1,2})?$/.test(typed) ? "0.00" : parseAmount(typed);
      if (amount === null) return { patch: null, error: `${f.label}: enter an amount such as 1299.00.` };
      patch.totals = { ...(patch.totals ?? d.totals), [f.key]: { amount, currency: d.totals.gross.currency } };
    } else if (f.key === "issue_date") {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(typed)) return { patch: null, error: "Date: use the form 2026-11-20." };
      patch.issue_date = typed;
    } else if (f.key === "seller_tax_id") patch.seller = { ...d.seller, tax_id: typed || null };
    else patch.buyer = { ...d.buyer, tax_id: typed || null };
  }
  return { patch: Object.keys(patch).length ? patch : null, error: null };
}

/** The who-paid banner: one headline, one consequence. */
export function whoPaid(m: Match | undefined): { headline: string; detail: string | null } | null {
  if (!m) return null;
  const who = firstName(m.payer?.name);
  const headline = {
    employee_private: `Paid privately by ${who}`,
    owner_private: "Paid with the owner's private card",
    company_account: "Paid from a company account",
    unknown: "Not clear yet who paid",
  }[m.paid_by];
  const owed = m.consequences.reimbursement_owed;
  return { headline, detail: owed ? `The company owes ${firstName(m.consequences.reimbursement_to?.name ?? m.payer?.name)} ${formatMoney(owed)}.` : null };
}

/** One short line per thing the owner should know about this document. */
export function flagNotes(d: OrdoDocument, m: Match | undefined): string[] {
  const notes: string[] = [];
  const has = (f: OrdoDocument["flags"][number]) => d.flags.includes(f);
  if (has("vat_not_deductible")) notes.push(`No company tax number: ${formatMoney(m?.consequences.vat_lost ?? d.totals.vat)} VAT cannot be recovered`);
  else if (has("buyer_not_company") || has("missing_tax_id")) notes.push("No company tax number on the document");
  if (has("foreign_currency") && d.totals.fx && d.totals.gross_base) notes.push(`${formatMoney(d.totals.gross)} = ${formatMoney(d.totals.gross_base)} at ${d.totals.fx.rate}`);
  if (has("reverse_charge")) notes.push("Bought abroad: you report the VAT yourself (reverse charge)");
  for (const f of ["possible_private", "duplicate_suspected", "amount_unclear", "low_confidence"] as const) if (has(f)) notes.push(words(f).replace(/^./, (c) => c.toUpperCase()));
  return notes;
}
