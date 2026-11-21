// Inbox logic with no React in it, so it can be tested directly.
import type { DecisionRequest, InboxResponse } from "../../api/client";
import { isRenderableRecommendation } from "../../api/guards";
import type { Approval, Money, Recommendation } from "../../api/types.gen";
import { shortDate } from "../../lib/dates";
import { formatMoney, isNegative } from "../../lib/money";

export const AGENT_LABEL: Record<Recommendation["agent"], string> = {
  ingestion: "Ingestion agent",
  liquidity: "Liquidity agent",
  tax: "Tax agent",
  fx: "FX Shield",
  chat: "Ask Ordo",
};

export type Filter = "all" | "approval" | "recommendation" | "decided";
export type Decided = { rec: Recommendation; approval: Approval };

const DECIDED_STATUS: ReadonlySet<Recommendation["status"]> = new Set(["approved", "rejected", "executed_simulated"]);
export const isDecided = (r: Recommendation): boolean => DECIDED_STATUS.has(r.status);

const isMoney = (v: unknown): v is Money => typeof v === "object" && v !== null && typeof (v as Money).amount === "string" && typeof (v as Money).currency === "string";

/** The one amount the owner may change before approving, per kind of action. */
const EDITABLE: Partial<Record<NonNullable<Recommendation["proposed_action"]>["kind"], { param: string; label: string }>> = {
  apply_credit_line: { param: "limit", label: "Limit" },
};

export function editableAmount(r: Recommendation): { param: string; label: string; value: Money } | null {
  const spec = r.proposed_action && EDITABLE[r.proposed_action.kind];
  const value = spec && r.proposed_action?.params[spec.param];
  return spec && isMoney(value) ? { ...spec, value } : null;
}

/**
 * Turns what the owner typed into a decimal string: "25 000" -> "25000.00", "25,000.5" -> "25000.50",
 * "1299,90" -> "1299.90". Returns null when it is not a positive amount. Text only, no floating point.
 */
export function parseAmount(input: string): string | null {
  let s = input.trim().replace(/[\s ]/g, "");
  if (/^\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(s)) s = s.replace(/,/g, "");
  else if (/^\d+,\d{1,2}$/.test(s)) s = s.replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  const [int, frac = ""] = s.split(".");
  if (!/[1-9]/.test(int + frac)) return null;
  return `${int.replace(/^0+(?=\d)/, "")}.${frac.padEnd(2, "0")}`;
}

/** An action can be approved here only if it needs approval and would run in simulation. */
export function canApprove(r: Recommendation): boolean {
  return r.control_level === "approval_required" && r.execution_mode === "simulated" && Boolean(r.proposed_action) && r.proposed_action?.kind !== "none";
}

/** The request body for the decision endpoint. `editedAmount` is the output of parseAmount. */
export function buildDecision(r: Recommendation, kind: "approve" | "reject", editedAmount?: string | null): DecisionRequest {
  if (kind === "reject") return { decision: "rejected", channel: "dashboard" };
  const edit = editableAmount(r);
  if (edit && editedAmount && editedAmount !== parseAmount(edit.value.amount)) {
    return { decision: "approved_with_changes", channel: "dashboard", changes: { [`proposed_action.params.${edit.param}`]: { amount: editedAmount, currency: edit.value.currency } } };
  }
  return { decision: "approved", channel: "dashboard" };
}

export type InboxLists = { open: Recommendation[]; decided: Recommendation[]; counts: Record<Filter, number>; approvalFor: (id: string) => Approval | undefined };

/**
 * What the page shows. Cards without control level, execution mode, explanation and evidence are
 * dropped (contracts rule 4). `justDecided` are decisions made on this page since it was opened.
 */
export function buildLists(inbox: InboxResponse, all: Recommendation[], approvals: Approval[], justDecided: Record<string, Decided> = {}): InboxLists {
  const open = inbox.items.filter(isRenderableRecommendation).filter((r) => !justDecided[r.id] && !isDecided(r));
  const decided = new Map<string, Recommendation>();
  for (const d of Object.values(justDecided)) decided.set(d.rec.id, d.rec);
  for (const r of all.filter(isRenderableRecommendation).filter(isDecided)) if (!decided.has(r.id)) decided.set(r.id, r);
  // A stored approval counts only for a card that is decided; an open card is never shown as approved.
  const approvalFor = (id: string) => justDecided[id]?.approval ?? (decided.has(id) ? approvals.find((a) => a.subject_type === "recommendation" && a.subject_id === id) : undefined);
  return {
    open,
    decided: [...decided.values()],
    counts: {
      all: open.length,
      approval: open.filter((r) => r.control_level === "approval_required").length,
      recommendation: open.filter((r) => r.control_level === "recommendation").length,
      decided: decided.size,
    },
    approvalFor,
  };
}

export function listFor(lists: InboxLists, filter: Filter): Recommendation[] {
  if (filter === "decided") return lists.decided;
  if (filter === "approval") return lists.open.filter((r) => r.control_level === "approval_required");
  if (filter === "recommendation") return lists.open.filter((r) => r.control_level === "recommendation");
  return lists.open;
}

export type Fact = { label: string; value: string; tone?: "danger" | "positive" };

/** The strip of key figures under the summary. Every number comes from the finance engine via `impact`. */
export function impactFacts(r: Recommendation): Fact[] {
  const facts: Fact[] = [];
  const i = r.impact;
  if (i?.min_balance_before) facts.push({ label: "Lowest balance now", value: formatMoney(i.min_balance_before, { decimals: false }), tone: isNegative(i.min_balance_before) ? "danger" : undefined });
  if (i?.min_balance_after) facts.push({ label: "After this action", value: formatMoney(i.min_balance_after, { decimals: false }), tone: isNegative(i.min_balance_after) ? "danger" : "positive" });
  if (i?.cash_effect && !i.min_balance_after) facts.push({ label: "Effect on cash", value: formatMoney(i.cash_effect, { decimals: false }) });
  if (i?.cost) facts.push({ label: "Estimated cost", value: formatMoney(i.cost) });
  if (r.valid_until) facts.push({ label: "Decide by", value: shortDate(r.valid_until) });
  return facts;
}

/** The headline of a finished decision, e.g. "Done — SIM-CL-2026-0007". */
export function resultHeadline(a: Approval): string {
  if (a.decision === "rejected") return "Rejected. Nothing was sent.";
  const mode = a.execution.mode === "none" ? "Recorded" : a.execution.mode === "simulated" ? "Done" : "Not run";
  if (a.execution.status === "failed") return `${mode} — failed`;
  if (a.execution.status === "pending") return `${mode} — in progress`;
  return a.execution.reference ? `${mode} — ${a.execution.reference}` : mode;
}

/** The owner's edits, readable: [["Limit", "25,000.00 PLN"]]. */
export function describeChanges(a: Approval): [string, string][] {
  return Object.entries(a.changes ?? {}).map(([path, value]) => {
    const name = path.split(".").at(-1) ?? path;
    return [name.charAt(0).toUpperCase() + name.slice(1).replaceAll("_", " "), isMoney(value) ? formatMoney(value) : String(value)];
  });
}
