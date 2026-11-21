// What To-do (and the To-do card on the Overview) shows, with no React in it.
// Only owner decisions are listed: an agent's advice that needs no answer ("info") and what Ordo
// did on its own stay out of the list.
import type { ActivityItem } from "../../api/client";
import { isRenderableRecommendation } from "../../api/guards";
import type { Approval, ControlLevel, Forecast, Money, Recommendation } from "../../api/types.gen";
import { abs, compareAmounts, isZero } from "../../lib/costTypes";
import { daysBetween, shortDate } from "../../lib/dates";
import { firstSentence, whole } from "../../lib/words";
import { canApprove, isDecided } from "../inbox/model";

/** What the approve button says. The button also carries a small "simulated" tag (SimButton, product rule). */
const APPROVE_LABEL: Partial<Record<Recommendation["type"], string>> = {
  reimburse_employee: "Pay back",
  credit_line: "Apply",
  chase_receivable: "Send reminder",
  payment_deferral: "Send the note",
  fx_hedge: "Fix the rate",
  tax_reserve: "Set aside",
};
export const approveLabel = (r: Recommendation): string => APPROVE_LABEL[r.type] ?? "Approve";

const CHECK_LABEL: Partial<Record<Recommendation["type"], string>> = { request_company_invoice: "See which" };
/** Liquidity actions that close a cash gap. They are shown together, as options under the gap. */
const GAP_OPTIONS: ReadonlySet<Recommendation["type"]> = new Set(["credit_line", "payment_deferral", "chase_receivable"]);

/** Cards that come in bulk (one per payment) become one to-do pointing to where they are checked one by one. */
const BULK: Partial<Record<Recommendation["type"], { title: (n: number) => string; summary: string; to: string; label: string }>> = {
  confirm_match: { title: (n) => `${n} invoices matched to payments`, summary: "Ordo paired each invoice with its bank line. Check them, so they go into the books.", to: "/money/payments?doc=to_check", label: "Check them" },
  missing_document: { title: (n) => `${n} payments have no invoice`, summary: "Without an invoice a cost can't go into the books, and its VAT can't be reclaimed.", to: "/money/payments?doc=missing", label: "See which" },
};

export type Gap = { from: string; to: string | null; days: number | null; lowest: { date: string; amount: Money }; short: Money; options: Recommendation[] };
export type Primary = { kind: "approve" | "details" | "link"; label: string; to?: string };
type Severity = Recommendation["severity"];
/** `addedAt`, `dueBy`, `amount` and `severity` are what the To-do list can be sorted by. */
export type TodoItem = {
  id: string; level: ControlLevel; title: string; summary: string; primary: Primary; rec?: Recommendation; gap?: Gap;
  addedAt: string | null; dueBy: string | null; amount: Money | null; severity: Severity;
};
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
    ? (canApprove(r) ? { kind: "approve", label: approveLabel(r) } : { kind: "details", label: "See details" })
    : link ? { kind: "link", label: CHECK_LABEL[r.type] ?? "Check", to: link } : { kind: "details", label: "See details" };
  const amount = r.impact?.cash_effect ?? r.impact?.cost ?? null;
  return {
    id: r.id, level: r.control_level, title: r.title, summary: firstSentence(r.summary), primary, rec: r,
    addedAt: r.created_at, dueBy: r.valid_until ?? null, amount: amount && !isZero(amount.amount) ? amount : null, severity: r.severity,
  };
}

export function buildTodo(items: Recommendation[], forecast: Forecast | null): Todo {
  const all = items.filter(isRenderableRecommendation).filter((r) => !isDecided(r) && r.type !== "info" && r.control_level !== "analysed_autonomously");
  const bulkItems: TodoItem[] = [];
  const bulked = new Set<string>();
  for (const [type, spec] of Object.entries(BULK) as [Recommendation["type"], NonNullable<(typeof BULK)[Recommendation["type"]]>][]) {
    const many = all.filter((r) => r.type === type);
    if (many.length < 2) continue;
    many.forEach((r) => bulked.add(r.id));
    bulkItems.push({
      id: `bulk-${type}`, level: many[0].control_level, title: spec.title(many.length), summary: spec.summary, primary: { kind: "link", label: spec.label, to: spec.to },
      addedAt: newest(many.map((r) => r.created_at)), dueBy: earliest(many.map((r) => r.valid_until)), amount: null, severity: worst(many.map((r) => r.severity)),
    });
  }
  const open = all.filter((r) => !bulked.has(r.id));
  const alert = forecast?.alerts.find((a) => a.type === "cash_gap") ?? null;
  // One option per kind of action: when an agent proposed the same kind twice, the newest proposal counts.
  const newestOfType = (r: Recommendation, _: number, list: Recommendation[]) => !list.some((o) => o.type === r.type && o.created_at > r.created_at);
  const candidates = alert ? open.filter((r) => r.agent === "liquidity" && GAP_OPTIONS.has(r.type)) : [];
  const options = candidates.filter(newestOfType).sort(byCost);
  const grouped = new Set(candidates.map((r) => r.id)); // older duplicates are hidden, not shown on their own
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
      addedAt: newest(options.map((r) => r.created_at)) ?? forecast.generated_at ?? null, dueBy: alert.date_from, amount: alert.max_shortfall, severity: "critical",
    };
  }
  const first = approvals.filter((r) => r.type === "reimburse_employee").map(single);
  const rest = approvals.filter((r) => r.type !== "reimburse_employee").map(single);
  const needsOk = [...first, ...(gapItem ? [gapItem] : []), ...rest, ...bulkItems.filter((i) => i.level === "approval_required")];
  const check = [...open.filter((r) => r.control_level === "recommendation").map(single), ...bulkItems.filter((i) => i.level !== "approval_required")];
  return { needsOk, check, count: needsOk.length + check.length };
}

const SEVERITY_RANK: Record<Severity, number> = { critical: 2, warning: 1, info: 0 };
const newest = (dates: (string | null | undefined)[]): string | null => dates.filter((d): d is string => Boolean(d)).sort().at(-1) ?? null;
const earliest = (dates: (string | null | undefined)[]): string | null => dates.filter((d): d is string => Boolean(d)).sort()[0] ?? null;
const worst = (list: Severity[]): Severity => list.reduce<Severity>((w, s) => (SEVERITY_RANK[s] > SEVERITY_RANK[w] ? s : w), "info");

export type TodoSort = "newest" | "oldest" | "urgent" | "due" | "amount";
export const TODO_SORTS: { key: TodoSort; label: string; hint: string }[] = [
  { key: "newest", label: "Newest first", hint: "The latest Ordo added comes first" },
  { key: "oldest", label: "Oldest first", hint: "What has waited longest comes first" },
  { key: "urgent", label: "Most urgent", hint: "Critical first, then by how soon it must be decided" },
  { key: "due", label: "Deadline soonest", hint: "What expires or is due first comes first" },
  { key: "amount", label: "Largest amount", hint: "The most money at stake comes first" },
];
export const isTodoSort = (s: unknown): s is TodoSort => TODO_SORTS.some((x) => x.key === s);

/** Missing values go last whatever the direction, so an item without a date never jumps to the top. */
const nullsLast = <T,>(a: T | null, b: T | null, cmp: (x: T, y: T) => number): number => (a === null ? (b === null ? 0 : 1) : b === null ? -1 : cmp(a, b));
const size = (m: Money) => abs(m.amount);

export function sortTodo(items: TodoItem[], by: TodoSort): TodoItem[] {
  const added = (a: TodoItem, b: TodoItem) => nullsLast(a.addedAt, b.addedAt, (x, y) => y.localeCompare(x));
  const due = (a: TodoItem, b: TodoItem) => nullsLast(a.dueBy, b.dueBy, (x, y) => x.localeCompare(y));
  const cmp: Record<TodoSort, (a: TodoItem, b: TodoItem) => number> = {
    newest: added,
    oldest: (a, b) => nullsLast(a.addedAt, b.addedAt, (x, y) => x.localeCompare(y)),
    urgent: (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || due(a, b) || added(a, b),
    due: (a, b) => due(a, b) || added(a, b),
    // Compares the decimal strings; amounts in another currency are not converted, this only orders the list.
    amount: (a, b) => nullsLast(a.amount, b.amount, (x, y) => compareAmounts(size(y), size(x))) || added(a, b),
  };
  return [...items].sort(cmp[by]);
}

/** The Overview's To-do card: the first two decisions and the first suggestion, three at most. */
export function topThree(todo: Todo): TodoItem[] {
  const ok = todo.needsOk.slice(0, 2);
  const check = todo.check.slice(0, Math.max(1, 3 - ok.length));
  return [...ok, ...check, ...todo.needsOk.slice(2)].slice(0, 3);
}

/** One line of the log. `level` "approved" means the owner decided it (`said_no` when the decision was a no). */
export type Done = {
  at: string; level: "analysed_autonomously" | "approved"; text: string; reference?: string | null; saidNo?: boolean;
  rec?: Recommendation; approval?: Approval; activity?: ActivityItem;
};

const ID_WORDS: Record<string, string> = { doc: "an invoice", txn: "a payment", mat: "a match", rec: "a to-do", led: "a booking", raw: "a file", cp: "a company" };

/** A log line as a short headline: no ids, no bracketed working ("Matched doc_1 to txn_2 (…)" -> "Matched an invoice to a payment"). */
export function headline(text: string): string {
  const short = text.replace(/\s*\(.*$/s, "").replace(/\b([a-z]+)_[A-Za-z0-9_]+\b/g, (id, prefix: string) => ID_WORDS[prefix] ?? id).replace(/\s+automatically$/, "").trim();
  return short.length > 90 ? `${short.slice(0, 87).trimEnd()}…` : short;
}

const OWNER_TEXT: Record<Approval["subject_type"], [yes: string, no: string]> = {
  recommendation: ["Approved action", "Said no to an action"],
  match: ["Confirmed an invoice and its payment", "Undid a match Ordo made"],
  ledger_entry: ["Confirmed a booking", "Rejected a booking"],
  document: ["Confirmed a document", "Rejected a document"],
};

/** Every owner decision as a log line, newest first. */
export function ownerLog(approvals: Approval[], recs: Recommendation[]): Done[] {
  return approvals.map((a) => {
    const rec = a.subject_type === "recommendation" ? recs.find((r) => r.id === a.subject_id) : undefined;
    const no = a.decision === "rejected";
    const text = rec ? (no ? `Said no: ${rec.title}` : rec.title) : OWNER_TEXT[a.subject_type][no ? 1 : 0];
    return { at: a.decided_at, level: "approved" as const, text, reference: a.execution.reference, saidNo: no, rec, approval: a };
  }).sort(newestFirst);
}

/** Everything Ordo did on its own as log lines, newest first. */
export const ordoLog = (activity: ActivityItem[]): Done[] =>
  activity.map((a) => ({ at: a.at, level: "analysed_autonomously" as const, text: a.text, activity: a })).sort(newestFirst);

const newestFirst = (a: Done, b: Done) => b.at.localeCompare(a.at);

/** What To-do shows under "Done recently": the actions the owner approved, and what Ordo did on its own. */
export function doneRecently(activity: ActivityItem[], approvals: Approval[], recs: Recommendation[], limit = 3): { approved: Done[]; alone: Done[] } {
  const approved = ownerLog(approvals, recs).filter((d) => d.approval?.subject_type === "recommendation" && !d.saidNo).slice(0, limit);
  return { approved, alone: ordoLog(activity).slice(0, limit) };
}

/** What can be undone from the app: an action the owner approved, or a match Ordo made on its own. */
export function undoKind(d: Done): "approval" | "match" | null {
  if (d.level === "approved") return d.approval && !d.saidNo && d.approval.subject_type === "recommendation" ? "approval" : null;
  return d.activity?.subject?.type === "match" ? "match" : null;
}

/** Log lines grouped by calendar day (UTC, like every date in the app), newest day first. */
export function byDay(lines: Done[]): [day: string, lines: Done[]][] {
  const days = new Map<string, Done[]>();
  for (const d of [...lines].sort(newestFirst)) days.set(d.at.slice(0, 10), [...(days.get(d.at.slice(0, 10)) ?? []), d]);
  return [...days.entries()];
}
