// What To-do (and the To-do card on the Overview) shows, with no React in it.
// Only owner decisions are listed: an agent's advice that needs no answer ("info") and what Ordo
// did on its own stay out of the list.
import type { ActivityItem } from "../../api/client";
import { isRenderableRecommendation } from "../../api/guards";
import type { Approval, ControlLevel, Forecast, Money, Recommendation } from "../../api/types.gen";
import { compareAmounts, isZero } from "../../lib/costTypes";
import { daysBetween, shortDate } from "../../lib/dates";
import { firstSentence, whole } from "../../lib/words";
import { canApprove, isDecided } from "../inbox/model";

/** Every button that runs something says SIMULATED (product rule). */
const APPROVE_LABEL: Partial<Record<Recommendation["type"], string>> = {
  reimburse_employee: "Pay back (simulated)",
  credit_line: "Apply (simulated)",
  chase_receivable: "Send reminder (simulated)",
  payment_deferral: "Send the note (simulated)",
  fx_hedge: "Fix the rate (simulated)",
  tax_reserve: "Set aside (simulated)",
};
export const approveLabel = (r: Recommendation): string => APPROVE_LABEL[r.type] ?? "Approve (simulated)";

const CHECK_LABEL: Partial<Record<Recommendation["type"], string>> = { request_company_invoice: "See which" };
/** Kinds of action simple enough to approve straight from the list; the rest open their details first. */
const ONE_CLICK: ReadonlySet<Recommendation["type"]> = new Set(["reimburse_employee"]);
/** Liquidity actions that close a cash gap. They are shown together, as options under the gap. */
const GAP_OPTIONS: ReadonlySet<Recommendation["type"]> = new Set(["credit_line", "payment_deferral", "chase_receivable"]);

/** Cards that come in bulk (one per payment) become one to-do pointing to where they are checked one by one. */
const BULK: Partial<Record<Recommendation["type"], { title: (n: number) => string; summary: string; to: string; label: string }>> = {
  confirm_match: { title: (n) => `${n} invoices matched to payments`, summary: "Ordo paired each invoice with its bank line. Check them, so they go into the books.", to: "/money/payments?doc=to_check", label: "Check them" },
  missing_document: { title: (n) => `${n} payments have no invoice`, summary: "Without an invoice a cost can't go into the books, and its VAT can't be reclaimed.", to: "/money/payments?doc=missing", label: "See which" },
};

export type Gap = { from: string; to: string | null; days: number | null; lowest: { date: string; amount: Money }; short: Money; options: Recommendation[] };
export type Primary = { kind: "approve" | "details" | "link"; label: string; to?: string };
export type TodoItem = { id: string; level: ControlLevel; title: string; summary: string; primary: Primary; rec?: Recommendation; gap?: Gap };
export type Todo = { needsOk: TodoItem[]; check: TodoItem[]; count: number };

/** "Free", "About 317 PLN", or null when the engine gave no cost. */
export function costLabel(r: Recommendation): string | null {
  const cost = r.impact?.cost;
  if (!cost) return null;
  return isZero(cost.amount) ? "Free" : `About ${whole(cost)}`;
}

const byCost = (a: Recommendation, b: Recommendation) =>
  a.impact?.cost && b.impact?.cost ? compareAmounts(a.impact.cost.amount, b.impact.cost.amount) : a.impact?.cost ? -1 : b.impact?.cost ? 1 : 0;

function single(r: Recommendation): TodoItem {
  const link = r.evidence.find((e) => e.url?.startsWith("/"))?.url;
  const primary: Primary = r.control_level === "approval_required"
    ? (canApprove(r) && ONE_CLICK.has(r.type) ? { kind: "approve", label: approveLabel(r) } : { kind: "details", label: "See details" })
    : link ? { kind: "link", label: CHECK_LABEL[r.type] ?? "Check", to: link } : { kind: "details", label: "See details" };
  return { id: r.id, level: r.control_level, title: r.title, summary: firstSentence(r.summary), primary, rec: r };
}

export function buildTodo(items: Recommendation[], forecast: Forecast | null): Todo {
  const all = items.filter(isRenderableRecommendation).filter((r) => !isDecided(r) && r.type !== "info" && r.control_level !== "analysed_autonomously");
  const bulkItems: TodoItem[] = [];
  const bulked = new Set<string>();
  for (const [type, spec] of Object.entries(BULK) as [Recommendation["type"], NonNullable<(typeof BULK)[Recommendation["type"]]>][]) {
    const many = all.filter((r) => r.type === type);
    if (many.length < 2) continue;
    many.forEach((r) => bulked.add(r.id));
    bulkItems.push({ id: `bulk-${type}`, level: many[0].control_level, title: spec.title(many.length), summary: spec.summary, primary: { kind: "link", label: spec.label, to: spec.to } });
  }
  const open = all.filter((r) => !bulked.has(r.id));
  const alert = forecast?.alerts.find((a) => a.type === "cash_gap") ?? null;
  // One option per kind of action: when an agent proposed the same kind twice, the newest proposal counts.
  const newestOfType = (r: Recommendation, _: number, list: Recommendation[]) => !list.some((o) => o.type === r.type && o.created_at > r.created_at);
  const options = alert ? open.filter((r) => r.agent === "liquidity" && GAP_OPTIONS.has(r.type)).filter(newestOfType).sort(byCost) : [];
  const grouped = new Set(options.map((r) => r.id));
  const approvals = open.filter((r) => r.control_level === "approval_required" && !grouped.has(r.id));

  let gapItem: TodoItem | null = null;
  if (alert && forecast) {
    const days = alert.date_to ? daysBetween(alert.date_from, alert.date_to) : null;
    const gap: Gap = { from: alert.date_from, to: alert.date_to ?? null, days, lowest: forecast.min_balance, short: alert.max_shortfall, options };
    const cause = options.find((r) => r.type === "credit_line") ?? options[0];
    const howLong = days ? `For ${days} day${days === 1 ? "" : "s"} you would be up to ${whole(alert.max_shortfall)} short.` : `You would be up to ${whole(alert.max_shortfall)} short.`;
    gapItem = {
      id: "gap", level: "approval_required",
      title: alert.date_to ? `Cash runs short from ${shortDate(alert.date_from)} to ${shortDate(alert.date_to)}` : `Cash runs short from ${shortDate(alert.date_from)}`,
      summary: cause ? `${firstSentence(cause.summary)} ${howLong}` : howLong,
      primary: { kind: "link", label: "See options", to: "/todo#gap" }, gap,
    };
  }
  const first = approvals.filter((r) => r.type === "reimburse_employee").map(single);
  const rest = approvals.filter((r) => r.type !== "reimburse_employee").map(single);
  const needsOk = [...first, ...(gapItem ? [gapItem] : []), ...rest, ...bulkItems.filter((i) => i.level === "approval_required")];
  const check = [...open.filter((r) => r.control_level === "recommendation").map(single), ...bulkItems.filter((i) => i.level !== "approval_required")];
  return { needsOk, check, count: needsOk.length + check.length };
}

/** The Overview's To-do card: the first two decisions and the first suggestion, three at most. */
export function topThree(todo: Todo): TodoItem[] {
  const ok = todo.needsOk.slice(0, 2);
  const check = todo.check.slice(0, Math.max(1, 3 - ok.length));
  return [...ok, ...check, ...todo.needsOk.slice(2)].slice(0, 3);
}

export type Done = { at: string; level: "analysed_autonomously" | "approved"; text: string; reference?: string | null };

/**
 * What happened lately: the owner's last approvals (with their simulated reference) and what Ordo did
 * alone, newest first. Ordo works far more often than the owner approves, so up to two approvals are
 * always kept in the list.
 */
export function doneRecently(activity: ActivityItem[], approvals: Approval[], recs: Recommendation[], limit = 3): Done[] {
  const newest = (a: Done, b: Done) => b.at.localeCompare(a.at);
  const approved: Done[] = approvals
    .filter((a) => a.subject_type === "recommendation" && a.decision !== "rejected")
    .map((a) => {
      const rec = recs.find((r) => r.id === a.subject_id);
      return { at: a.decided_at, level: "approved" as const, text: `${rec?.title ?? "Approved action"} · ${shortDate(a.decided_at)}`, reference: a.execution.reference };
    })
    .sort(newest).slice(0, Math.min(2, limit));
  const alone: Done[] = activity.map((a) => ({ at: a.at, level: "analysed_autonomously" as const, text: a.text })).sort(newest).slice(0, limit - approved.length);
  return [...approved, ...alone].sort(newest);
}
