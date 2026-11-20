// How names, categories and amounts are worded on screen.
import type { Money } from "../api/types.gen";
import { formatMoney } from "./money";

/** Sample data marks every invented name "(SAMPLE)" (hard rule 2). Screens say SAMPLE once, next to the company, and show names without it. */
export const plainName = (name?: string | null): string => (name ?? "").replace(/\s*\(SAMPLE\)\s*$/i, "").trim();
export const firstName = (name?: string | null): string => plainName(name).split(/\s+/)[0] ?? "";
export const initials = (name?: string | null): string =>
  plainName(name).split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** "Borsuk Labs sp. z o.o. (SAMPLE)" -> { main: "Borsuk Labs", sub: "sp. z o.o. · SAMPLE" } */
export function companyLines(name: string): { main: string; sub: string } {
  const tag = /\(([^)]+)\)\s*$/.exec(name)?.[1] ?? null;
  const rest = name.replace(/\s*\([^)]+\)\s*$/, "").trim();
  const legal = /\s(sp\. z o\.o\.|S\.A\.|GmbH|Inc\.|Ltd\.?)$/.exec(rest)?.[1] ?? null;
  return { main: legal ? rest.slice(0, -legal.length).trim() : rest, sub: [legal, tag].filter(Boolean).join(" · ") };
}

/** Whole units, as on the Overview: "38,400 PLN". */
export const whole = (m: Money | null | undefined): string => formatMoney(m, { decimals: false });
export const words = (s: string): string => s.replaceAll("_", " ");
export const sentenceCase = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);
/** The first sentence of an agent's summary: the point, without the explanation. */
export const firstSentence = (s: string): string => /^.*?[.!?](?=\s|$)/.exec(s.trim())?.[0] ?? s;
export const pct = (share: number): string => `${Math.round(share * 100)}%`;

/** The contract's categories (D-09) in an owner's words. */
export const CATEGORY_LABEL: Record<string, string> = {
  revenue_services: "Client payment", salaries: "Salaries", contractors: "Contractors", social_security: "Social security", taxes: "Taxes",
  rent_office: "Office rent", software_subscriptions: "Software", cloud_hosting: "Hosting", equipment: "Equipment", travel: "Travel",
  marketing_ads: "Ads", professional_services: "Accounting and legal", bank_fees: "Bank fees", meals_representation: "Meals with clients",
  reimbursements: "Paid back to the team", owner_private: "Personal", financing: "Loans and credit", investment_outflow: "Investments", other: "Not explained yet",
};
export const categoryLabel = (c?: string | null): string => CATEGORY_LABEL[c ?? "other"] ?? sentenceCase(words(c ?? "other"));

export const ROLE_LABEL: Record<string, string> = { owner: "Owner", employee: "Employee", contractor: "Contractor", accountant: "Accountant" };
export const PAY_LABEL: Record<string, string> = { salary: "Salary", invoice: "Invoice", board_fee: "Board fee" };
