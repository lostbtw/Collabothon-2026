// Mock mode: answers every API path in contracts/openapi.yaml from contracts/fixtures.
// The response shapes follow the OpenAPI spec so that live mode needs no code change.
import accountsJson from "@contracts/fixtures/account.json";
import approvalsJson from "@contracts/fixtures/approval.json";
import counterpartiesJson from "@contracts/fixtures/counterparty.json";
import documentsJson from "@contracts/fixtures/document.json";
import eventsJson from "@contracts/fixtures/event.json";
import forecastsJson from "@contracts/fixtures/forecast.json";
import ledgerJson from "@contracts/fixtures/ledger_entry.json";
import matchesJson from "@contracts/fixtures/match.json";
import rawItemsJson from "@contracts/fixtures/raw_item.json";
import recommendationsJson from "@contracts/fixtures/recommendation.json";
import sourcesJson from "@contracts/fixtures/source.json";
import syncRunsJson from "@contracts/fixtures/sync_run.json";
import transactionsJson from "@contracts/fixtures/transaction.json";
import { formatMoney } from "../lib/money";
import type {
  Account, Approval, Counterparty, Forecast, LedgerEntry, Match, Money, OrdoDocument, OrdoEvent, RawItem, Recommendation, Source, SyncRun, Transaction,
} from "./types.gen";

export const fixtures = {
  accounts: accountsJson as unknown as Account[],
  approvals: approvalsJson as unknown as Approval[],
  counterparties: counterpartiesJson as unknown as Counterparty[],
  documents: documentsJson as unknown as OrdoDocument[],
  events: eventsJson as unknown as OrdoEvent[],
  forecasts: forecastsJson as unknown as Forecast[],
  ledger: ledgerJson as unknown as LedgerEntry[],
  matches: matchesJson as unknown as Match[],
  rawItems: rawItemsJson as unknown as RawItem[],
  recommendations: recommendationsJson as unknown as Recommendation[],
  sources: sourcesJson as unknown as Source[],
  syncRuns: syncRunsJson as unknown as SyncRun[],
  transactions: transactionsJson as unknown as Transaction[],
};

class MockNotFound extends Error {
  status = 404;
}

const COMPANIES = [
  { id: "co_borsuk", name: "Borsuk Labs sp. z o.o. (SAMPLE)", base_currency: "PLN", country: "PL", as_of_date: "2026-11-21" },
  { id: "co_amalfi", name: "Pizzeria Amalfi (organisers' data)", base_currency: "EUR", country: "DE", as_of_date: "2025-05-15" },
];

// Not in the fixtures yet: the "What I did on my own" feed. Numbers follow the demo script in the role 6 spec.
const ACTIVITY = [
  { at: "2026-11-21T10:14:56Z", agent: "ingestion", text: "Read Jan's receipt and worked out that he paid privately", subject: { type: "document", id: "doc_rcpt412" }, evidence: [{ kind: "document", id: "doc_rcpt412", label: "Receipt", url: "/documents/doc_rcpt412" }] },
  { at: "2026-11-21T10:00:00Z", agent: "ingestion", text: "Read 1,480 items from 5 sources", subject: null, evidence: [{ kind: "external", id: "sources", label: "Sources", url: "/sources" }] },
  { at: "2026-11-21T09:58:00Z", agent: "ingestion", text: "Merged 61 duplicates, such as one PixelBoard invoice that arrived three times", subject: { type: "document", id: "doc_pixel11" }, evidence: [{ kind: "document", id: "doc_pixel11", label: "PixelBoard invoice", url: "/documents/doc_pixel11" }] },
  { at: "2026-11-21T09:57:00Z", agent: "ingestion", text: "Matched 212 payments, including a 45.00 USD invoice to a 180.62 PLN card line", subject: { type: "match", id: "mat_pixel11" }, evidence: [{ kind: "match", id: "mat_pixel11", label: "Cross-currency match", url: "/matches/mat_pixel11" }] },
];

// Not in the fixtures either: the copies of the PixelBoard invoice that were merged into one record.
// The kept record came by e-mail; the same invoice also arrived as an e-invoice and as a photo.
const COPIES: OrdoDocument[] = (["ksef", "photo"] as const).map((channel) => {
  const original = (documentsJson as unknown as OrdoDocument[]).find((d) => d.id === "doc_pixel11")!;
  return { ...original, id: `doc_pixel11_${channel}`, channel, duplicate_of: original.id, status: "duplicate" };
});

// Decisions made in this tab. The fixtures never change; this sits on top of them so that an approved
// card leaves the inbox and shows up as decided, the way the real API behaves.
const decisions = new Map<string, Approval>();
const documentEdits = new Map<string, OrdoDocument>();
const undoneMatches = new Set<string>();
const syncedAt = new Map<string, string>();
// The mock's clock: the demo moment, moving forward from when the page was opened.
const DEMO_START = Date.parse("2026-11-21T10:15:00Z");
const openedAt = Date.now();
const demoNow = (): string => new Date(DEMO_START + (Date.now() - openedAt)).toISOString();
export function resetMockState(): void {
  decisions.clear();
  documentEdits.clear();
  undoneMatches.clear();
  syncedAt.clear();
}

/** Applies a partial correction to a document, level by level (totals.gross replaces only gross). */
function mergeDeep<T>(base: T, patch: unknown): T {
  if (typeof patch !== "object" || patch === null || Array.isArray(patch) || typeof base !== "object" || base === null) return patch as T;
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(patch)) out[k] = "amount" in (patch as object) ? v : mergeDeep(out[k], v);
  return out as T;
}
const withDecision = (r: Recommendation): Recommendation => {
  const a = decisions.get(r.id);
  return a ? { ...r, status: a.decision === "rejected" ? "rejected" : "executed_simulated", approval_id: a.id } : r;
};

type DecisionBody = { decision?: Approval["decision"]; comment?: string | null; changes?: Record<string, unknown> | null; channel?: Approval["channel"] };

/** What the sandbox bank would answer. Amounts are echoed from the request, never calculated here. */
function mockDecide(rec: Recommendation, body: DecisionBody = {}): Approval {
  const template = fixtures.approvals[0];
  const decision = body.decision ?? "approved";
  const params = (rec.proposed_action?.params ?? {}) as Record<string, unknown>;
  const money = (key: string) => formatMoney((body.changes?.[`proposed_action.params.${key}`] ?? params[key]) as Money | undefined);
  const outcomes: Record<string, () => { reference: string; result: string; effects?: Approval["execution"]["effects"] }> = {
    apply_credit_line: () => ({ reference: "SIM-CL-2026-0007", result: `Sandbox bank accepted the application: limit ${money("limit")}, available from 2026-11-27.`, effects: template.execution.effects }),
    create_payment_draft: () => ({ reference: "SIM-PAY-2026-0412", result: `Sandbox bank added a transfer draft of ${money("amount")} to the payment run on ${String(params.pay_on)}.` }),
    book_fx_forward: () => ({ reference: "SIM-FX-2026-0003", result: `Sandbox bank booked the forward: sell ${money("notional")} at ${String(params.rate)}, value date ${String(params.value_date)}.` }),
  };
  const outcome = (outcomes[rec.proposed_action?.kind ?? "none"] ?? (() => ({ reference: `SIM-${rec.id.toUpperCase()}`, result: "Recorded in the sandbox." })))();
  const approval: Approval = {
    id: `apr_mock_${decisions.size + 1}`,
    subject_type: "recommendation",
    subject_id: rec.id,
    decision,
    decided_by: template.decided_by,
    decided_at: template.decided_at,
    channel: body.channel ?? "dashboard",
    comment: body.comment ?? null,
    changes: body.changes ?? null,
    execution: decision === "rejected"
      ? { mode: rec.execution_mode, status: "not_applicable", executed_at: null, reference: null, result: "Rejected. Nothing was sent.", effects: [] }
      : { mode: "simulated", status: "done", executed_at: template.execution.executed_at, reference: outcome.reference, result: outcome.result, effects: outcome.effects ?? [] },
  };
  decisions.set(rec.id, approval);
  return approval;
}

const byCompany = <T,>(items: T[], companyId: string | null): T[] =>
  companyId ? items.filter((i) => (i as { company_id?: string }).company_id === undefined || (i as { company_id?: string }).company_id === companyId) : items;

function find<T extends { id: string }>(items: T[], id: string): T {
  const hit = items.find((i) => i.id === id);
  if (!hit) throw new MockNotFound(`No fixture with id ${id}`);
  return hit;
}

export async function mockRequest<T>(method: string, url: string, body?: unknown): Promise<T> {
  const parsed = new URL(url, "http://mock.local");
  const path = parsed.pathname.replace(/\/$/, "");
  const q = parsed.searchParams;
  const company = q.get("company_id");
  const seg = path.split("/").filter(Boolean);
  const f = { ...fixtures, recommendations: fixtures.recommendations.map(withDecision), documents: fixtures.documents.map((d) => documentEdits.get(d.id) ?? d) };
  const page = <I,>(items: I[]) => ({ items, next_cursor: null });
  let result: unknown;

  if (method === "GET" && path === "/health") result = { status: "ok", llm: { base_url: "mock", model: "mock", reachable: false }, demo_clock: demoNow() };
  else if (method === "GET" && path === "/companies") result = { items: COMPANIES };
  else if (method === "GET" && path === "/sources")
    result = { items: byCompany(f.sources, company).map((s) => (syncedAt.has(s.id) ? { ...s, last_synced_at: syncedAt.get(s.id), last_success_at: syncedAt.get(s.id) } : s)) };
  else if (method === "POST" && seg[0] === "sources" && seg[2] === "sync") {
    const at = demoNow();
    syncedAt.set(find(f.sources, seg[1]).id, at);
    result = { ...f.syncRuns[0], source_id: seg[1], trigger: "manual", started_at: at, finished_at: at };
  }
  else if (method === "GET" && path === "/sync-runs") result = { items: f.syncRuns.filter((r) => !q.get("source_id") || r.source_id === q.get("source_id")) };
  else if (method === "GET" && seg[0] === "raw-items" && seg.length === 2) result = find(f.rawItems, seg[1]);
  else if (method === "GET" && path === "/documents")
    result = page(byCompany(f.documents, company).filter((d) => (!q.get("status") || d.status === q.get("status")) && (!q.get("direction") || d.direction === q.get("direction"))));
  else if ((method === "GET" || method === "PATCH") && seg[0] === "documents" && seg.length === 2) {
    const document = find(f.documents, seg[1]);
    if (method === "PATCH") {
      const edited = mergeDeep(document, body);
      documentEdits.set(document.id, edited);
      result = edited;
    } else result = { document, duplicates: [...f.documents, ...COPIES].filter((d) => d.duplicate_of === document.id), matches: f.matches.filter((m) => m.document_id === document.id) };
  } else if (method === "GET" && path === "/accounts") {
    const items = byCompany(f.accounts, company);
    const forecast = byCompany(f.forecasts, company)[0];
    result = { items, total_liquidity_base: forecast?.opening_balance ?? null };
  } else if (method === "GET" && path === "/transactions") result = page(f.transactions.filter((t) => !q.get("account_id") || t.account_id === q.get("account_id")));
  else if (method === "GET" && seg[0] === "transactions" && seg.length === 2) result = find(f.transactions, seg[1]);
  else if (method === "GET" && path === "/counterparties") result = { items: byCompany(f.counterparties, company) };
  else if (method === "GET" && path === "/matches")
    result = { items: f.matches.map((m) => (undoneMatches.has(m.id) ? { ...m, status: "rejected" as const } : m)).filter((m) => !q.get("status") || m.status === q.get("status")) };
  else if (method === "GET" && path === "/inbox") {
    const items = byCompany(f.recommendations, company).filter((r) => r.status === "new" || r.status === "seen");
    result = { items, counts: { approval_required: items.filter((r) => r.control_level === "approval_required").length, recommendation: items.filter((r) => r.control_level === "recommendation").length, analysed_autonomously_today: ACTIVITY.length } };
  } else if (method === "GET" && path === "/ledger") result = page(byCompany(f.ledger, company));
  else if (method === "GET" && path === "/ledger/summary")
    result = { rows: [], kpis: { reimbursements_owed: { amount: "5169.00", currency: "PLN" }, vat_lost_ytd: { amount: "242.90", currency: "PLN" }, documents_missing: 3, tax_due_next_30d: { amount: "25200.00", currency: "PLN" } } };
  else if (seg[0] === "forecast" && (method === "POST" || seg.length === 2)) {
    const forecast = (seg[1] && f.forecasts.find((x) => x.id === seg[1])) || byCompany(f.forecasts, company)[0] || f.forecasts[0];
    result = forecast;
  } else if (method === "GET" && path === "/recommendations")
    result = { items: byCompany(f.recommendations, company).filter((r) => (!q.get("status") || r.status === q.get("status")) && (!q.get("agent") || r.agent === q.get("agent")) && (!q.get("control_level") || r.control_level === q.get("control_level"))) };
  else if (method === "GET" && seg[0] === "recommendations" && seg.length === 2) result = find(f.recommendations, seg[1]);
  else if (method === "POST" && seg[0] === "recommendations" && seg[2] === "decision") result = mockDecide(find(fixtures.recommendations, seg[1]), body as DecisionBody | undefined);
  else if (method === "POST" && seg[0] === "matches" && seg[2] === "decision") {
    const decision = (body as DecisionBody | undefined)?.decision ?? "approved";
    if (decision === "rejected") undoneMatches.add(find(f.matches, seg[1]).id);
    result = { ...f.approvals[0], subject_type: "match", subject_id: seg[1], decision, changes: null, comment: null, execution: { mode: "none", status: "not_applicable", executed_at: null, reference: null, result: null, effects: [] } };
  } else if (method === "GET" && path === "/approvals") result = { items: [...decisions.values()] };
  else if (method === "GET" && path === "/activity") result = { items: ACTIVITY.filter((a) => !(a.subject?.type === "match" && undoneMatches.has(a.subject.id))) };
  else if (method === "POST" && path === "/chat") {
    const forecast = f.forecasts[0];
    result = {
      session_id: "mock-session",
      answer: `Mock answer. The lowest projected balance is ${forecast.min_balance.amount.amount} ${forecast.min_balance.amount.currency} on ${forecast.min_balance.date}; the account first goes below zero on ${forecast.first_negative_date}.`,
      evidence: [{ kind: "forecast", id: forecast.id, label: "45-day forecast", url: `/forecast/${forecast.id}` }],
      table: null, tool_calls: [{ tool: "get_forecast", arguments: { horizon_days: forecast.horizon_days }, duration_ms: 12 }], created_recommendation_id: null, guardrail: null, trace_id: null,
    };
  } else if (method === "GET" && path === "/fx/rates") result = f.documents.find((d) => d.totals.fx)?.totals.fx ?? null;
  else if (method === "GET" && path === "/fx/exposure")
    result = { items: f.recommendations.filter((r) => r.agent === "fx").map((r) => ({ document_id: r.subject?.id ?? null, verdict: r.type === "fx_hedge" ? "hedge_proposed" : "not_worth_it", recommendation_id: r.id })) };
  else throw new MockNotFound(`Mock mode has no handler for ${method} ${path}`);

  // Fixtures are shared module state: hand out copies so a page cannot mutate them.
  return structuredClone(result) as T;
}

/** Mock event stream: replays contracts/fixtures/event.json once, one event every `intervalMs`. */
export function mockEventStream(onEvent: (e: OrdoEvent) => void, intervalMs = 1500): () => void {
  const timers = fixtures.events.map((e, i) => setTimeout(() => onEvent(structuredClone(e)), intervalMs * (i + 1)));
  return () => timers.forEach(clearTimeout);
}
