import type { Money } from "../api/types.gen";

/** Formats a Money value for display from its decimal string; amounts never become floating point. */
export function formatMoney(m: Money | null | undefined, opts: { decimals?: boolean } = {}): string {
  if (!m) return "—";
  const negative = m.amount.startsWith("-");
  const [int, frac = ""] = m.amount.replace(/^-/, "").split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const showDecimals = opts.decimals ?? true;
  return `${negative ? "-" : ""}${grouped}${showDecimals ? "." + frac.padEnd(2, "0").slice(0, 2) : ""} ${m.currency}`;
}

export const isNegative = (m: Money | null | undefined): boolean => Boolean(m && m.amount.startsWith("-") && /[1-9]/.test(m.amount));
