// Typed API client. Entity types are generated from contracts/schemas (types.gen.ts);
// the response envelopes below follow contracts/openapi.yaml. The calls marked "promised" are the
// endpoints role 1 is adding; until the live API has them they return null and the screen says so.
import { API_BASE, API_MODE } from "../config";
import { mockEventStream } from "./mock";
import { http, httpForm, optional, type Query } from "./transport";
import type {
  Account, Approval, Counterparty, EvidenceLink, Forecast, FxConversion, LedgerEntry, Match, Money, OrdoDocument, OrdoEvent, RawItem, Recommendation, Source, SyncRun, Transaction,
} from "./types.gen";

export type Page<T> = { items: T[]; next_cursor: string | null };
export type Company = { id: string; name: string; base_currency: string; country: string; as_of_date?: string };
export type Health = { status: "ok"; llm: { base_url: string; model: string; reachable: boolean }; demo_clock: string };
export type DocumentDetail = { document: OrdoDocument; duplicates: OrdoDocument[]; matches: Match[] };
export type AccountsResponse = { items: Account[]; total_liquidity_base: Money | null };
export type InboxResponse = { items: Recommendation[]; counts: { approval_required: number; recommendation: number; analysed_autonomously_today: number } };
export type LedgerSummary = {
  rows: { key: string; amount_base: Money; previous_period?: Money | null; change_pct: number | null; entries: number }[];
  kpis: { reimbursements_owed: Money; vat_lost_ytd: Money; documents_missing: number; tax_due_next_30d?: Money | null };
};
/** One foreign-currency invoice and what a bad exchange rate could cost on it (FX Shield). */
export type FxExposure = {
  document_id: string | null; direction?: string; amount: Money; value_today_base?: Money; expected_cash_date?: string; horizon_days?: number;
  expected_shortfall?: Money | null; deal_profit?: Money | null; verdict: string; recommendation_id?: string | null;
};
export type ActivityItem = { at: string; agent: string; text: string; subject?: { type: string; id: string } | null; evidence: EvidenceLink[] };
/** Partial Document: only totals, dates, seller, buyer and category_suggestion.category may be corrected.
 * Each of those is sent whole (the API validates the block it receives), with only the corrected value changed. */
export type DocumentPatch = { issue_date?: string; totals?: OrdoDocument["totals"]; seller?: OrdoDocument["seller"]; buyer?: OrdoDocument["buyer"]; category_suggestion?: OrdoDocument["category_suggestion"] };
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

// ---- Promised endpoints (shapes agreed with role 1; see the prompt in the design notes) ----
export type BalanceHistory = { currency: string; points: { date: string; balance: string }[] };
/** `parts` (optional): what the cost is made of, e.g. salary + social security. */
export type PersonCost = { person_id: string; name: string; role: string; pay_type: string | null; paid: Money; payments: number; owed: Money; receipts_owed: number; parts?: { label: string; amount: Money }[] };
export type PeopleCosts = { items: PersonCost[]; totals: { staff: Money; social_security: Money; share_of_costs: number } };
export type OpenInvoice = { document_id: string; number: string | null; gross: Money; gross_base: Money; due_date: string | null; days_late: number };
export type ClientRow = {
  counterparty_id: string; name: string; currency: string; paid_in_month: Money; open_invoices: OpenInvoice[]; open_total_base: Money;
  typical_payment_delay_days: number | null; share_of_income: number;
};
export type ClientsResponse = { items: ClientRow[]; totals: { paid_in_month: Money; open_base: Money; late_base: Money } };
/** Optional extras: `previous_monthly` (the price before it went up), `duplicate_cost` (what one of the double payments costs). */
export type Subscription = {
  counterparty_id: string; name: string; category: string; monthly: Money; original: Money | null;
  paid_by: { kind: "account" | "card" | "person"; label: string }[]; flags: string[]; series_ids: string[];
  previous_monthly?: Money | null; duplicate_cost?: Money | null;
  /** False when the payment is expected this month but not paid yet (monthly = last month's amount). */
  paid_in_month?: boolean;
};
export type SubscriptionsResponse = { items: Subscription[]; monthly_total: Money };
export type Settings = {
  company: { id: string; name: string; tax_id: string | null; base_currency: string; vat_period: "monthly" | "quarterly"; accountant_email: string | null };
  alerts: { safety_buffer: Money | null; late_client_days: number; weekly_summary: boolean };
};
export type Person = { id: string; name: string; email: string; role: string; pay_type: string | null; card_last4: string[]; statement_names: string[]; tax_id: string | null; iban: string | null };
export type Rule = { id: string; raw: string; counterparty_id: string; counterparty_name: string; category: string | null; learned_at: string | null };
export type ChatSession = { session_id: string; title: string; last_at: string; messages: number };
export type ChatSessionDetail = { session_id: string; messages: { role: "user" | "assistant"; content: string; at: string }[] };

const co = (company_id?: string): Query => ({ company_id });

export const api = {
  health: () => http<Health>("GET", "/health"),
  companies: () => http<{ items: Company[] }>("GET", "/companies"),
  sources: (companyId?: string) => http<{ items: Source[] }>("GET", "/sources", { query: co(companyId) }),
  syncNow: (sourceId: string) => http<SyncRun>("POST", `/sources/${sourceId}/sync`),
  syncRuns: (sourceId?: string) => http<{ items: SyncRun[] }>("GET", "/sync-runs", { query: { source_id: sourceId } }),
  rawItem: (id: string) => http<RawItem>("GET", `/raw-items/${id}`),
  documents: (companyId?: string, filter: { status?: string; direction?: string } = {}) => http<Page<OrdoDocument>>("GET", "/documents", { query: { ...co(companyId), ...filter } }),
  document: (id: string) => http<DocumentDetail>("GET", `/documents/${id}`),
  patchDocument: (id: string, body: DocumentPatch) => http<OrdoDocument>("PATCH", `/documents/${id}`, { body }),
  accounts: (companyId?: string) => http<AccountsResponse>("GET", "/accounts", { query: co(companyId) }),
  transactions: (companyId?: string, accountId?: string) => http<Page<Transaction>>("GET", "/transactions", { query: { ...co(companyId), account_id: accountId } }),
  counterparties: (companyId?: string) => http<{ items: Counterparty[] }>("GET", "/counterparties", { query: co(companyId) }),
  matches: (companyId?: string, status?: string) => http<{ items: Match[] }>("GET", "/matches", { query: { ...co(companyId), status } }),
  inbox: (companyId?: string) => http<InboxResponse>("GET", "/inbox", { query: co(companyId) }),
  ledger: (companyId?: string) => http<Page<LedgerEntry>>("GET", "/ledger", { query: co(companyId) }),
  /** `basis: "bank"` sums the bank lines per category instead of the books: for months whose payments are not booked yet. */
  ledgerSummary: (companyId?: string, opts: { groupBy?: string; from?: string; to?: string; basis?: "ledger" | "bank" } = {}) =>
    http<LedgerSummary>("GET", "/ledger/summary", { query: { ...co(companyId), group_by: opts.groupBy, from: opts.from, to: opts.to, basis: opts.basis } }),
  /** The owner changes a bank line's type; Ordo remembers it as a rule for that counterparty. */
  setTransactionCategory: (id: string, category: string, companyId?: string) =>
    optional(http<Transaction>("PATCH", `/transactions/${id}`, { query: co(companyId), body: { category } })),
  forecast: (companyId?: string, horizonDays = 45) => http<Forecast>("GET", "/forecast/latest", { query: { ...co(companyId), horizon_days: horizonDays } }),
  /** `status` narrows the list (all recommendations together are over a megabyte on real data). */
  recommendations: (companyId?: string, status?: Recommendation["status"]) => http<{ items: Recommendation[] }>("GET", "/recommendations", { query: { ...co(companyId), status } }),
  recommendation: (id: string) => http<Recommendation>("GET", `/recommendations/${id}`),
  decideMatch: (matchId: string, body: DecisionRequest) => http<Approval>("POST", `/matches/${matchId}/decision`, { body }),
  decide: (recommendationId: string, body: DecisionRequest) => http<Approval>("POST", `/recommendations/${recommendationId}/decision`, { body }),
  approvals: (companyId?: string) => http<{ items: Approval[] }>("GET", "/approvals", { query: co(companyId) }),
  activity: (companyId?: string) => http<{ items: ActivityItem[] }>("GET", "/activity", { query: co(companyId) }),
  chat: (message: string, companyId?: string, sessionId?: string | null) => http<ChatAnswer>("POST", "/chat", { body: { message, company_id: companyId, session_id: sessionId ?? null } }),
  fxExposure: (companyId?: string) => http<{ items: FxExposure[] }>("GET", "/fx/exposure", { query: co(companyId) }),
  fxRate: (currency: string, date: string) => http<FxConversion | null>("GET", "/fx/rates", { query: { currency, date } }),
  /** A receipt or invoice the owner adds by hand. `transactionId` tells Ordo which payment it belongs to. */
  upload: (file: File, opts: { companyId?: string; submittedBy?: string; transactionId?: string } = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.submittedBy) form.append("submitted_by", opts.submittedBy);
    if (opts.transactionId) form.append("transaction_id", opts.transactionId);
    return httpForm<RawItem>("/uploads", form, co(opts.companyId));
  },

  // Promised (null until the live API serves them)
  balanceHistory: (companyId?: string) => optional(http<BalanceHistory>("GET", "/balance/history", { query: co(companyId) })),
  peopleCosts: (companyId: string | undefined, month: string) => optional(http<PeopleCosts>("GET", "/people/costs", { query: { ...co(companyId), month } })),
  clients: (companyId: string | undefined, month: string) => optional(http<ClientsResponse>("GET", "/clients", { query: { ...co(companyId), month } })),
  /** scope "all": every payment that repeats each month (rent, staff, taxes); default: only tools and services. */
  subscriptions: (companyId?: string, month?: string, scope?: "subscriptions" | "all") =>
    optional(http<SubscriptionsResponse>("GET", "/subscriptions", { query: { ...co(companyId), month, scope } })),
  settings: (companyId?: string) => optional(http<Settings>("GET", "/settings", { query: co(companyId) })),
  patchSettings: (companyId: string | undefined, body: { company?: Partial<Settings["company"]>; alerts?: Partial<Settings["alerts"]> }) =>
    optional(http<Settings>("PATCH", "/settings", { query: co(companyId), body })),
  people: (companyId?: string) => optional(http<{ items: Person[] }>("GET", "/people", { query: co(companyId) })),
  addPerson: (companyId: string | undefined, body: Omit<Person, "id">) => optional(http<Person>("POST", "/people", { query: co(companyId), body })),
  updatePerson: (id: string, companyId: string | undefined, body: Partial<Omit<Person, "id">>) =>
    optional(http<Person>("PATCH", `/people/${id}`, { query: co(companyId), body })),
  rules: (companyId?: string) => optional(http<{ items: Rule[] }>("GET", "/rules", { query: co(companyId) })),
  deleteRule: (id: string, companyId?: string) => optional(http<void>("DELETE", `/rules/${id}`, { query: co(companyId) })),
  chatSessions: (companyId?: string) => optional(http<{ items: ChatSession[] }>("GET", "/chat/sessions", { query: co(companyId) })),
  chatSession: (id: string, companyId?: string) => optional(http<ChatSessionDetail>("GET", `/chat/sessions/${id}`, { query: co(companyId) })),
};

/** Where the original file of a raw item (photo, PDF) is served. Null in mock mode: fixtures carry no files. */
export const rawContentUrl = (rawItemId: string): string | null => (API_MODE === "mock" ? null : `${API_BASE}/raw-items/${rawItemId}/content`);
/** The CSV export of everything (live only). */
export const exportUrl = (companyId: string): string | null => (API_MODE === "mock" ? null : `${API_BASE}/ledger/export?company_id=${encodeURIComponent(companyId)}`);

/** Every event type of the contract. A Record so the compiler complains when the contract gains a type. */
export const EVENT_TYPES: Record<OrdoEvent["type"], true> = {
  "sync.run.started": true, "sync.run.finished": true, "raw_item.received": true, "document.extracted": true, "document.duplicate_detected": true,
  "transaction.ingested": true, "match.suggested": true, "match.decided": true, "ledger.entry.proposed": true, "ledger.entry.approved": true,
  "forecast.updated": true, "recommendation.created": true, "recommendation.status_changed": true, "approval.recorded": true, "execution.simulated": true,
};

/** Live updates (Server-Sent Events). Returns an unsubscribe function. */
export function subscribeEvents(onEvent: (e: OrdoEvent) => void, companyId?: string): () => void {
  if (API_MODE === "mock") return mockEventStream(onEvent);
  const source = new EventSource(`${API_BASE}/events/stream${companyId ? `?company_id=${encodeURIComponent(companyId)}` : ""}`);
  const deliver = (m: MessageEvent<string>) => onEvent(JSON.parse(m.data) as OrdoEvent);
  // The API names each SSE message after its event type ("event: document.extracted"), and a named
  // message never reaches onmessage: listen for every type, and keep onmessage for unnamed ones.
  for (const type of Object.keys(EVENT_TYPES)) source.addEventListener(type, deliver as EventListener);
  source.onmessage = deliver;
  return () => source.close();
}
