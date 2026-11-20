// Typed API client. Entity types are generated from contracts/schemas (types.gen.ts);
// the response envelopes below follow contracts/openapi.yaml.
import { API_BASE, API_MODE } from "../config";
import { mockEventStream } from "./mock";
import { http, type Query } from "./transport";
import type {
  Account, Approval, Counterparty, EvidenceLink, Forecast, FxConversion, LedgerEntry, Match, Money, OrdoDocument, OrdoEvent, Recommendation, Source, SyncRun, Transaction,
} from "./types.gen";

export type Page<T> = { items: T[]; next_cursor: string | null };
export type Company = { id: string; name: string; base_currency: string; country: string };
export type Health = { status: "ok"; llm: { base_url: string; model: string; reachable: boolean }; demo_clock: string };
export type DocumentDetail = { document: OrdoDocument; duplicates: OrdoDocument[]; matches: Match[] };
export type AccountsResponse = { items: Account[]; total_liquidity_base: Money | null };
export type InboxResponse = { items: Recommendation[]; counts: { approval_required: number; recommendation: number; analysed_autonomously_today: number } };
export type LedgerSummary = {
  rows: { key: string; amount_base: Money; previous_period: Money; change_pct: number | null; entries: number }[];
  kpis: { reimbursements_owed: Money; vat_lost_ytd: Money; documents_missing: number; tax_due_next_30d: Money };
};
export type ActivityItem = { at: string; agent: string; text: string; evidence: EvidenceLink[] };
export type DecisionRequest = { decision: Approval["decision"]; comment?: string | null; changes?: Record<string, unknown> | null; channel?: "dashboard" | "chat" };
export type ChatAnswer = {
  session_id: string;
  answer: string;
  evidence: EvidenceLink[];
  table?: { columns: string[]; rows: unknown[][]; sql: string } | null;
  tool_calls?: { tool: string; arguments: Record<string, unknown>; duration_ms: number }[];
  created_recommendation_id?: string | null;
  guardrail?: { blocked: boolean; reason: string } | null;
  trace_id?: string | null;
};

const co = (company_id?: string): Query => ({ company_id });

export const api = {
  health: () => http<Health>("GET", "/health"),
  companies: () => http<{ items: Company[] }>("GET", "/companies"),
  sources: (companyId?: string) => http<{ items: Source[] }>("GET", "/sources", { query: co(companyId) }),
  syncNow: (sourceId: string) => http<SyncRun>("POST", `/sources/${sourceId}/sync`),
  syncRuns: (sourceId?: string) => http<{ items: SyncRun[] }>("GET", "/sync-runs", { query: { source_id: sourceId } }),
  documents: (companyId?: string, filter: { status?: string; direction?: string } = {}) => http<Page<OrdoDocument>>("GET", "/documents", { query: { ...co(companyId), ...filter } }),
  document: (id: string) => http<DocumentDetail>("GET", `/documents/${id}`),
  accounts: (companyId?: string) => http<AccountsResponse>("GET", "/accounts", { query: co(companyId) }),
  transactions: (companyId?: string, accountId?: string) => http<Page<Transaction>>("GET", "/transactions", { query: { ...co(companyId), account_id: accountId } }),
  counterparties: (companyId?: string) => http<{ items: Counterparty[] }>("GET", "/counterparties", { query: co(companyId) }),
  matches: (companyId?: string, status?: string) => http<{ items: Match[] }>("GET", "/matches", { query: { ...co(companyId), status } }),
  inbox: (companyId?: string) => http<InboxResponse>("GET", "/inbox", { query: co(companyId) }),
  ledger: (companyId?: string) => http<Page<LedgerEntry>>("GET", "/ledger", { query: co(companyId) }),
  ledgerSummary: (companyId?: string) => http<LedgerSummary>("GET", "/ledger/summary", { query: co(companyId) }),
  forecast: (companyId?: string, horizonDays = 45) => http<Forecast>("GET", "/forecast/latest", { query: { ...co(companyId), horizon_days: horizonDays } }),
  recommendations: (companyId?: string) => http<{ items: Recommendation[] }>("GET", "/recommendations", { query: co(companyId) }),
  recommendation: (id: string) => http<Recommendation>("GET", `/recommendations/${id}`),
  decide: (recommendationId: string, body: DecisionRequest) => http<Approval>("POST", `/recommendations/${recommendationId}/decision`, { body }),
  approvals: (companyId?: string) => http<{ items: Approval[] }>("GET", "/approvals", { query: co(companyId) }),
  activity: (companyId?: string) => http<{ items: ActivityItem[] }>("GET", "/activity", { query: co(companyId) }),
  chat: (message: string, companyId?: string, sessionId?: string | null) => http<ChatAnswer>("POST", "/chat", { body: { message, company_id: companyId, session_id: sessionId ?? null } }),
  fxRate: (currency: string, date: string) => http<FxConversion | null>("GET", "/fx/rates", { query: { currency, date } }),
};

/** Live updates (Server-Sent Events). Returns an unsubscribe function. Used by the toasts ticket. */
export function subscribeEvents(onEvent: (e: OrdoEvent) => void, companyId?: string): () => void {
  if (API_MODE === "mock") return mockEventStream(onEvent);
  const source = new EventSource(`${API_BASE}/events/stream${companyId ? `?company_id=${encodeURIComponent(companyId)}` : ""}`);
  source.onmessage = (m) => onEvent(JSON.parse(m.data) as OrdoEvent);
  return () => source.close();
}
