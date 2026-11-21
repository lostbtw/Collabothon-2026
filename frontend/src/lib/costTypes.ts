// Groups the contract's fixed category list into a few cost types an owner understands; presentation only.
import type { LedgerSummary } from "../api/client";
import type { Money } from "../api/types.gen";

export type CostType = { key: string; label: string; color: string; tag: string; categories: string[]; own?: boolean };

export const DEFAULT_COST_TYPES: CostType[] = [
  { key: "staff", label: "Staff", color: "var(--cat-1)", tag: "Fixed", categories: ["salaries", "contractors", "social_security"] },
  { key: "taxes", label: "Taxes", color: "var(--cat-2)", tag: "Monthly", categories: ["taxes"] },
  { key: "tools", label: "Tools & hosting", color: "var(--cat-3)", tag: "Every month", categories: ["software_subscriptions", "cloud_hosting"] },
  { key: "travel", label: "Travel & food", color: "var(--cat-4)", tag: "Varies", categories: ["travel", "meals_representation"] },
  { key: "equipment", label: "Equipment", color: "var(--cat-5)", tag: "One-off", categories: ["equipment", "investment_outflow", "financing"] },
  { key: "office", label: "Office", color: "var(--cat-6)", tag: "Fixed", categories: ["rent_office"] },
  { key: "services", label: "Services", color: "var(--cat-7)", tag: "Varies", categories: ["professional_services", "marketing_ads", "bank_fees"] },
  { key: "unexplained", label: "Not explained yet", color: "var(--cat-none)", tag: "Needs a look", categories: ["other"] },
];

export const FIXED_CATEGORIES = new Set(["salaries", "contractors", "social_security", "rent_office", "software_subscriptions", "cloud_hosting"]);
export const INCOME_CATEGORIES = new Set(["revenue_services"]);
export const NOT_COSTS = new Set(["reimbursements", "owner_private"]);

const OWN_KEY = "ordo.costTypes.own";
export const OWN_COLORS = ["#0f8b8d", "#a3478f", "#8c6d1f", "#4b6a88", "#c2452d", "#5c7d2e"];
export const ASSIGNABLE_CATEGORIES = DEFAULT_COST_TYPES.flatMap((t) => t.categories).filter((c) => c !== "other");

function readOwn(): CostType[] {
  try {
    const list = JSON.parse(globalThis.localStorage?.getItem(OWN_KEY) ?? "[]") as CostType[];
    return Array.isArray(list) ? list.map((t) => ({ ...t, own: true })) : [];
  } catch {
    return [];
  }
}
let own: CostType[] = readOwn();

export const ownCostTypes = (): CostType[] => own;

export function saveOwnCostTypes(list: CostType[]): void {
  own = list.map((t) => ({ ...t, own: true }));
  try { globalThis.localStorage?.setItem(OWN_KEY, JSON.stringify(own)); } catch { /* kept until reload */ }
}

export function costTypes(): CostType[] {
  const taken = new Set(own.flatMap((t) => t.categories));
  const defaults = DEFAULT_COST_TYPES.map((t) => ({ ...t, categories: t.categories.filter((c) => !taken.has(c)) }));
  const unexplained = defaults.pop()!;
  return [...defaults.filter((t) => t.categories.length > 0), ...own, unexplained];
}

export const typeOfCategory = (category: string): CostType => {
  const all = costTypes();
  return all.find((t) => t.categories.includes(category)) ?? all[all.length - 1];
};

// Exact decimal arithmetic on money strings, in cents, so no float ever touches an amount.
const cents = (amount: string): bigint => {
  const negative = amount.trim().startsWith("-");
  const [int, frac = ""] = amount.replace(/^[-+]/, "").split(".");
  const value = BigInt(int || "0") * 100n + BigInt((frac + "00").slice(0, 2));
  return negative ? -value : value;
};
const fromCents = (value: bigint): string => {
  const negative = value < 0n;
  const abs = negative ? -value : value;
  return `${negative ? "-" : ""}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
};
export const add = (a: string, b: string): string => fromCents(cents(a) + cents(b));
export const negate = (a: string): string => fromCents(-cents(a));
export const subtract = (a: string, b: string): string => fromCents(cents(a) - cents(b));
export const compareAmounts = (a: string, b: string): number => (cents(a) < cents(b) ? -1 : cents(a) > cents(b) ? 1 : 0);
export const abs = (a: string): string => fromCents(cents(a) < 0n ? -cents(a) : cents(a));
export const isZero = (a: string): boolean => cents(a) === 0n;
export const percent = (part: string, whole: string): number => {
  const w = cents(whole);
  return w === 0n ? 0 : Math.round((Number(cents(part)) / Number(w)) * 100);
};

export type MonthFigures = {
  currency: string;
  income: Money;
  costs: Money;
  leftOver: Money;
  fixed: Money;
  other: Money;
  unexplained: Money;
  types: { type: CostType; amount: Money; categories: { key: string; amount: Money }[] }[];
  hasData: boolean;
};

export function monthFigures(summary: LedgerSummary | null, currency: string): MonthFigures {
  const zero = "0.00";
  let income = zero, costs = zero, fixed = zero, unexplained = zero;
  const byType = new Map<string, { key: string; amount: string }[]>();
  for (const row of summary?.rows ?? []) {
    if (NOT_COSTS.has(row.key)) continue;
    if (INCOME_CATEGORIES.has(row.key)) { income = add(income, row.amount_base.amount); continue; }
    const out = negate(row.amount_base.amount);
    costs = add(costs, out);
    if (FIXED_CATEGORIES.has(row.key)) fixed = add(fixed, out);
    if (row.key === "other") unexplained = add(unexplained, out);
    const t = typeOfCategory(row.key);
    byType.set(t.key, [...(byType.get(t.key) ?? []), { key: row.key, amount: out }]);
  }
  const m = (amount: string): Money => ({ amount, currency });
  const types = costTypes().filter((t) => byType.has(t.key)).map((t) => {
    const cats = byType.get(t.key)!;
    return { type: t, amount: m(cats.reduce((s, c) => add(s, c.amount), zero)), categories: cats.map((c) => ({ key: c.key, amount: m(c.amount) })) };
  }).filter((t) => !isZero(t.amount.amount));
  return {
    currency, income: m(income), costs: m(costs), leftOver: m(add(income, negate(costs))), fixed: m(fixed),
    other: m(add(costs, negate(fixed))), unexplained: m(unexplained), types, hasData: (summary?.rows.length ?? 0) > 0,
  };
}

export function monthRange(month: string): { from: string; to: string } {
  const [y, mo] = month.split("-").map(Number);
  const last = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, "0")}` };
}

export function previousMonth(month: string): string {
  const [y, mo] = month.split("-").map(Number);
  return mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`;
}

export const lastFullMonth = (date: string): string => previousMonth(date.slice(0, 7));

export const monthName = (month: string): string =>
  new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${month}-15T12:00:00Z`));
export const monthOnly = (month: string): string =>
  new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(new Date(`${month}-15T12:00:00Z`));

export function recentMonths(today: string, n = 6): string[] {
  const out = [today.slice(0, 7)];
  while (out.length < n) out.push(previousMonth(out[out.length - 1]));
  return out;
}
