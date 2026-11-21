// One list of every payment: bank and card lines plus receipts paid with a private card. No React, so it is testable.
import type { Account, Counterparty, Match, Money, OrdoDocument, Transaction } from "../../api/types.gen";
import { NOT_COSTS, costTypes, negate, typeOfCategory } from "../../lib/costTypes";
import { categoryLabel, firstName, plainName } from "../../lib/words";

/** Where the paper behind a payment stands. */
export type DocState = "on_file" | "receipt" | "missing" | "not_needed" | "to_check";
export const DOC_CHIP: Record<DocState, { text: string; tone: string }> = {
  on_file: { text: "Invoice", tone: "neutral" },
  receipt: { text: "Receipt", tone: "neutral" },
  missing: { text: "Missing", tone: "bad" },
  not_needed: { text: "Not needed", tone: "neutral" },
  to_check: { text: "To check", tone: "warn" },
};

export type Payment = {
  id: string;
  date: string;
  name: string;
  category: string | null;
  /** In the company's currency; negative = money out. */
  amount: Money;
  /** The amount in the currency it was paid in, when that differs. */
  original: Money | null;
  paidBy: string;
  doc: DocState;
  transaction: Transaction | null;
  account: Account | null;
  document: OrdoDocument | null;
  match: Match | null;
};

export type PaymentInput = { transactions: Transaction[]; accounts: Account[]; counterparties: Counterparty[]; matches: Match[]; documents: OrdoDocument[] };

/** "Company account PLN" -> "PLN account". */
export function accountShort(a: Account | null): string {
  if (!a) return "Account";
  if (a.kind === "owner_private") return "Owner's card";
  const currency = /\b([A-Z]{3})$/.exec(a.name)?.[1];
  return currency ? `${currency} account` : a.name;
}

/** Which account or card the money went from (or came into), in a few words. */
function paidBy(t: Transaction, a: Account | null): string {
  if (!t.amount_base.amount.startsWith("-")) return `Into ${accountShort(a)}`;
  if (a?.kind === "owner_private") return `Owner's card${t.card_last4 ? ` ·${t.card_last4}` : ""}`;
  if (a?.kind === "employee_out_of_pocket") return `${firstName(a.name)}, own card`;
  return t.transaction_type === "card_payment" || t.card_last4 ? `Card ·${t.card_last4 ?? ""} (${accountShort(a).replace(" account", "")})` : accountShort(a);
}

function docState(t: Transaction, m: Match | null, d: OrdoDocument | null): DocState {
  if (m?.status === "suggested" || t.match_status === "suggested") return "to_check";
  if (t.match_status === "matched") return d?.doc_type === "receipt" ? "receipt" : "on_file";
  if (t.match_status === "no_document_needed") return "not_needed";
  return "missing";
}

export function buildPayments({ transactions, accounts, counterparties, matches, documents }: PaymentInput): Payment[] {
  const account = new Map(accounts.map((a) => [a.id, a]));
  const party = new Map(counterparties.map((c) => [c.id, c]));
  const doc = new Map(documents.map((d) => [d.id, d]));
  const live = matches.filter((m) => m.status !== "rejected");

  const bank: Payment[] = transactions.map((t) => {
    const m = live.filter((x) => x.transaction_id === t.id).at(-1) ?? null;
    const d = m ? doc.get(m.document_id) ?? null : null;
    const a = account.get(t.account_id) ?? null;
    return {
      id: t.id, date: t.booking_date,
      name: plainName(party.get(t.counterparty_id ?? "")?.name) || plainName(d?.seller.name) || t.counterparty_name_raw || t.description,
      category: t.category ?? d?.category_suggestion?.category ?? null,
      amount: t.amount_base,
      original: t.original_amount ?? (t.amount.currency !== t.amount_base.currency ? t.amount : null),
      paidBy: paidBy(t, a), doc: docState(t, m, d), transaction: t, account: a, document: d, match: m,
    };
  });

  const privately: Payment[] = live
    .filter((m) => m.match_type === "document_no_transaction" && (m.paid_by === "employee_private" || m.paid_by === "owner_private"))
    .flatMap((m) => {
      const d = doc.get(m.document_id);
      if (!d) return [];
      const gross = d.totals.gross_base ?? d.totals.gross;
      return [{
        id: d.id, date: d.issue_date ?? d.created_at?.slice(0, 10) ?? "", name: plainName(d.seller.name), category: d.category_suggestion?.category ?? null,
        amount: { amount: negate(gross.amount), currency: gross.currency }, original: gross.currency !== d.totals.gross.currency ? d.totals.gross : null,
        paidBy: m.paid_by === "owner_private" ? "Owner's card" : `${firstName(m.payer?.name) || "Employee"}, own card`,
        doc: d.doc_type === "receipt" ? ("receipt" as const) : ("on_file" as const), transaction: null, account: null, document: d, match: m,
      }];
    });

  return [...bank, ...privately].sort((a, b) => b.date.localeCompare(a.date) || a.name.localeCompare(b.name));
}

const isIncome = (p: Payment) => !p.amount.amount.startsWith("-") && p.category !== "reimbursements";

/** The key a payment is grouped under: a cost type (staff, taxes, ...), "income", or a not-a-cost category. */
export function typeKey(p: Payment): string {
  if (isIncome(p)) return "income";
  if (p.category && NOT_COSTS.has(p.category)) return p.category;
  return typeOfCategory(p.category ?? "other").key;
}

/** The coloured dot and words under the payment's name. */
export function typeOf(p: Payment): { label: string; color: string } {
  const key = typeKey(p);
  if (key === "income") return { label: "Client payment", color: "var(--accent)" };
  if (p.category && NOT_COSTS.has(p.category)) return { label: categoryLabel(p.category), color: "var(--cat-none)" };
  const t = costTypes().find((c) => c.key === key) ?? typeOfCategory("other");
  return { label: t.label, color: t.color };
}

export type PaymentFilter = { month?: string | null; type?: string | null; doc?: string | null; q?: string | null; account?: string | null };

export function filterPayments(list: Payment[], f: PaymentFilter): Payment[] {
  const q = f.q?.trim().toLowerCase();
  return list.filter((p) =>
    (!f.month || p.date.startsWith(f.month))
    && (!f.type || typeKey(p) === f.type)
    && (!f.doc || p.doc === f.doc)
    && (!f.account || (f.account === "private" ? !p.account : p.account?.id === f.account))
    && (!q || [p.name, p.paidBy, p.transaction?.counterparty_name_raw, p.transaction?.description, p.document?.seller.name, p.match?.payer?.name, typeOf(p).label]
      .some((s) => s?.toLowerCase().includes(q))));
}
