// Mock mode: answers every API path the app calls from contracts/fixtures plus sample.ts, in the live API's shapes.
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
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import type { ChatAnswer, Person, Settings, SpeechLanguage, Transcript } from "./client";
import {
  BALANCE_HISTORY, CHAT_HISTORY, MONTHLY_EXTRA, PEOPLE, PEOPLE_COSTS, RULES, SAMPLE_APPROVALS, SAMPLE_COUNTERPARTIES, SAMPLE_RECOMMENDATIONS, SAMPLE_TRANSACTIONS,
  SETTINGS, SUBSCRIPTIONS, SUMMARY_BY_MONTH, SUMMARY_KPIS, clientsFor, readUpload,
} from "./sample";
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

class MockRefused extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TRANSCRIBE_MS = 700;
const HEARD: Record<SpeechLanguage, string> = {
  pl: "Ile mam gotówki?",
  en: "How much cash do I have?",
  ru: "Сколько у меня денег?",
};

const COMPANIES = [
  { id: "co_borsuk", name: "Borsuk Labs sp. z o.o. (SAMPLE)", base_currency: "PLN", country: "PL", as_of_date: "2026-11-21" },
  { id: "co_amalfi", name: "Pizzeria Amalfi (organisers' data)", base_currency: "EUR", country: "DE", as_of_date: "2025-05-15" },
];

const ACTIVITY = [
  { at: "2026-11-21T10:14:56Z", agent: "ingestion", text: "Read Jan's receipt and worked out that he paid privately", subject: { type: "document", id: "doc_rcpt412" }, evidence: [{ kind: "document", id: "doc_rcpt412", label: "Receipt", url: "/documents/doc_rcpt412" }] },
  { at: "2026-11-21T10:00:00Z", agent: "ingestion", text: "Read 1,480 items from 5 sources", subject: null, evidence: [{ kind: "external", id: "sources", label: "Sources", url: "/settings#accounts" }] },
  { at: "2026-11-21T09:58:00Z", agent: "ingestion", text: "Merged 61 duplicates, such as one PixelBoard invoice that arrived three times", subject: { type: "document", id: "doc_pixel11" }, evidence: [{ kind: "document", id: "doc_pixel11", label: "PixelBoard invoice", url: "/documents/doc_pixel11" }] },
  { at: "2026-11-21T09:57:00Z", agent: "ingestion", text: "Matched 212 payments, including a 45.00 USD invoice to a 185.57 PLN card line", subject: { type: "match", id: "mat_pixel11" }, evidence: [{ kind: "match", id: "mat_pixel11", label: "Cross-currency match", url: "/matches/mat_pixel11" }] },
];

const FX_EXPOSURE = [
  { document_id: "doc_fvlake01", direction: "receivable", amount: { amount: "40000.00", currency: "USD" }, value_today_base: { amount: "162452.00", currency: "PLN" }, expected_cash_date: "2027-01-05", horizon_days: 45, expected_shortfall: { amount: "-6595.00", currency: "PLN" }, deal_profit: { amount: "8000.00", currency: "PLN" }, verdict: "hedge_proposed", recommendation_id: "rec_fx01" },
  { document_id: "doc_fv1007", direction: "receivable", amount: { amount: "18400.00", currency: "EUR" }, value_today_base: { amount: "81989.00", currency: "PLN" }, horizon_days: 45, expected_shortfall: { amount: "-1426.00", currency: "PLN" }, verdict: "not_worth_it", recommendation_id: "rec_fx02" },
];

const COPIES: OrdoDocument[] = (["ksef", "photo"] as const).map((channel) => {
  const original = (documentsJson as unknown as OrdoDocument[]).find((d) => d.id === "doc_pixel11")!;
  return { ...original, id: `doc_pixel11_${channel}`, channel, duplicate_of: original.id, status: "duplicate" };
});

const decisions = new Map<string, Approval>();
const documentEdits = new Map<string, OrdoDocument>();
const undoneMatches = new Set<string>();
const confirmedMatches = new Set<string>();
const categoryEdits = new Map<string, Transaction["category"]>();
const syncedAt = new Map<string, string>();
type Upload = { raw: RawItem; doc: OrdoDocument; match: Match | null; readyAt: number };
const uploads: Upload[] = [];
type Session = { session_id: string; company_id: string; title: string; last_at: string; messages: { role: "user" | "assistant"; content: string; at: string }[] };
let sessions: Session[] = [];
let settings: Settings = structuredClone(SETTINGS);
let people: Person[] = structuredClone(PEOPLE);
let rules = structuredClone(RULES);
const READ_MS = 1500;

const DEMO_START = Date.parse("2026-11-21T10:15:00Z");
const openedAt = Date.now();
const demoNow = (): string => new Date(DEMO_START + (Date.now() - openedAt)).toISOString();

function initialSessions(): Session[] {
  return CHAT_HISTORY.map(({ session_id, title, last_at, detail }) => ({ session_id, company_id: "co_borsuk", title, last_at, messages: structuredClone(detail) }));
}
sessions = initialSessions();

export function resetMockState(): void {
  decisions.clear();
  documentEdits.clear();
  undoneMatches.clear();
  confirmedMatches.clear();
  categoryEdits.clear();
  syncedAt.clear();
  uploads.length = 0;
  sessions = initialSessions();
  settings = structuredClone(SETTINGS);
  people = structuredClone(PEOPLE);
  rules = structuredClone(RULES);
}

export function finishMockReads(): void {
  for (const u of uploads) u.readyAt = 0;
}

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
const allRecommendations = (): Recommendation[] => [...fixtures.recommendations, ...SAMPLE_RECOMMENDATIONS];

type DecisionBody = { decision?: Approval["decision"]; comment?: string | null; changes?: Record<string, unknown> | null; channel?: Approval["channel"] };

function mockDecide(rec: Recommendation, body: DecisionBody = {}): Approval {
  const template = fixtures.approvals[0];
  const decision = body.decision ?? "approved";
  const params = (rec.proposed_action?.params ?? {}) as Record<string, unknown>;
  const money = (key: string) => formatMoney((body.changes?.[`proposed_action.params.${key}`] ?? params[key]) as Money | undefined);
  const outcomes: Record<string, () => { reference: string; result: string; effects?: Approval["execution"]["effects"] }> = {
    apply_credit_line: () => ({ reference: "SIM-CL-2026-0007", result: `Commerzbank accepted the application: limit ${money("limit")}, available from 2026-11-27.`, effects: template.execution.effects }),
    create_payment_draft: () => ({ reference: "SIM-PAY-2026-0412", result: `Commerzbank added a transfer draft of ${money("amount")} to the payment run on ${String(params.pay_on)}.` }),
    book_fx_forward: () => ({ reference: "SIM-FX-2026-0003", result: `Commerzbank booked the forward: sell ${money("notional")} at ${String(params.rate)}, value date ${String(params.value_date)}.` }),
    send_email_draft: () => ({ reference: `SIM-MAIL-2026-${String(21 + decisions.size).padStart(4, "0")}`, result: `Draft e-mail to ${String(params.to)} prepared.` }),
  };
  const outcome = (outcomes[rec.proposed_action?.kind ?? "none"] ?? (() => ({ reference: `SIM-${rec.id.toUpperCase()}`, result: "Recorded in the sandbox." })))();
  const approval: Approval = {
    id: `apr_mock_${decisions.size + 1}`,
    subject_type: "recommendation",
    subject_id: rec.id,
    decision,
    decided_by: template.decided_by,
    decided_at: demoNow(),
    channel: body.channel ?? "dashboard",
    comment: body.comment ?? null,
    changes: body.changes ?? null,
    execution: decision === "rejected"
      ? { mode: rec.execution_mode, status: "not_applicable", executed_at: null, reference: null, result: "Rejected. Nothing was sent.", effects: [] }
      : { mode: "simulated", status: "done", executed_at: demoNow(), reference: outcome.reference, result: outcome.result, effects: outcome.effects ?? [] },
  };
  decisions.set(rec.id, approval);
  return approval;
}

function mockAnswer(message: string, forecast: Forecast): Pick<ChatAnswer, "answer" | "evidence"> {
  const reply = (answer: string, ...evidence: ChatAnswer["evidence"]) => ({ answer, evidence });
  if (/\bjan\b/i.test(message)) return reply(CHAT_HISTORY[0].detail[1].content, { kind: "external", id: "per_jan", label: "Jan's costs", url: "/money/people" }, { kind: "match", id: "mat_412", label: "Owed to Jan", url: "/matches/mat_412" });
  if (/hire|developer/i.test(message)) return reply(CHAT_HISTORY[0].detail[3].content, { kind: "forecast", id: forecast.id, label: "Cash forecast", url: "/" });
  if (/cost/i.test(message)) return reply(CHAT_HISTORY[1].detail[1].content, { kind: "external", id: "2026-10", label: "October by type", url: "/money?month=2026-10" });
  if (/owe/i.test(message)) return reply(CHAT_HISTORY[2].detail[1].content, { kind: "external", id: "clients", label: "Clients", url: "/money/clients" });
  if (/bonus|afford/i.test(message)) {
    const accounts = fixtures.accounts.filter((a) => a.company_id === "co_borsuk").map((a) => ({ kind: "external" as const, id: a.id, label: `Account ${a.name}`, url: `/accounts/${a.id}` }));
    const lines = SAMPLE_TRANSACTIONS.filter((t) => t.amount_base.amount.startsWith("-")).map((t) => ({ kind: "transaction" as const, id: t.id, label: `${t.counterparty_name_raw}, ${t.booking_date}, ${formatMoney(t.amount_base)}`, url: `/transactions/${t.id}` }));
    return reply(CHAT_HISTORY[5].detail[1].content, ...accounts, { kind: "forecast", id: forecast.id, label: "Cash forecast", url: "/" }, ...lines);
  }
  return reply(
    `The lowest point is ${formatMoney(forecast.min_balance.amount, { decimals: false })} on ${shortDate(forecast.min_balance.date)}${forecast.first_negative_date ? `; the balance first goes below zero on ${shortDate(forecast.first_negative_date)}` : ""}.`,
    { kind: "forecast", id: forecast.id, label: "45-day forecast", url: "/" },
  );
}

const byCompany = <T,>(items: T[], companyId: string | null): T[] =>
  companyId ? items.filter((i) => (i as { company_id?: string }).company_id === undefined || (i as { company_id?: string }).company_id === companyId) : items;

function find<T extends { id: string }>(items: T[], id: string): T {
  const hit = items.find((i) => i.id === id);
  if (!hit) throw new MockNotFound(`No fixture with id ${id}`);
  return hit;
}

const onlyBorsuk = (company: string | null, what: string) => {
  if (company && company !== "co_borsuk") throw new MockNotFound(`No sample ${what} for ${company}`);
};

export async function mockRequest<T>(method: string, url: string, body?: unknown): Promise<T> {
  const parsed = new URL(url, "http://mock.local");
  const path = parsed.pathname.replace(/\/$/, "");
  const q = parsed.searchParams;
  const company = q.get("company_id");
  const seg = path.split("/").filter(Boolean);
  const read = uploads.filter((u) => Date.now() >= u.readyAt);
  const matchStatus = (m: Match): Match["status"] => (undoneMatches.has(m.id) ? "rejected" : confirmedMatches.has(m.id) ? "confirmed" : m.status);
  const matches = [...fixtures.matches, ...read.flatMap((u) => (u.match ? [u.match] : []))].map((m) => ({ ...m, status: matchStatus(m) }));
  const f = {
    ...fixtures,
    recommendations: allRecommendations().map(withDecision),
    documents: [...fixtures.documents, ...read.map((u) => u.doc)].map((d) => documentEdits.get(d.id) ?? d),
    counterparties: [...fixtures.counterparties, ...SAMPLE_COUNTERPARTIES],
    rawItems: [...fixtures.rawItems, ...uploads.map((u) => u.raw)],
    matches,
    transactions: [...fixtures.transactions, ...SAMPLE_TRANSACTIONS].map((t) => {
      const m = matches.filter((x) => x.transaction_id === t.id && x.status !== "rejected").at(-1);
      const typed = categoryEdits.has(t.id) ? { ...t, category: categoryEdits.get(t.id)! } : t;
      return m && t.match_status !== "matched" ? { ...typed, match_status: m.status === "suggested" ? ("suggested" as const) : ("matched" as const) } : typed;
    }),
  };
  const page = <I,>(items: I[]) => ({ items, next_cursor: null });
  let result: unknown;

  if (method === "GET" && path === "/health") result = { status: "ok", llm: { base_url: "mock", model: "mock", reachable: false }, speech: { model: "mock", reachable: true }, demo_clock: demoNow() };
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
  else if (method === "POST" && path === "/uploads") {
    const fields = (body ?? {}) as Record<string, string>;
    const n = uploads.length + 1;
    const t = f.transactions.find((x) => x.id === fields.transaction_id);
    const raw: RawItem = {
      id: `raw_upload_${n}`, source_id: "src_upload", sync_run_id: `run_upload_${n}`, kind: "upload", external_id: fields.file ?? `upload-${n}`,
      idempotency_key: `upload:${n}`, fetched_at: demoNow(), received_at: demoNow(), content_type: "image/jpeg", metadata: { filename: fields.file ?? null, transaction_id: fields.transaction_id ?? null },
      processing_status: "queued",
    };
    const sellerName = f.counterparties.find((c) => c.id === t?.counterparty_id)?.name ?? t?.counterparty_name_raw ?? "Seller (SAMPLE)";
    const doc = readUpload(`doc_upload_${n}`, raw.id, t, sellerName);
    const match: Match | null = t ? {
      id: `mat_upload_${n}`, match_type: "document_transaction", document_id: doc.id, transaction_id: t.id, score: 0.95, paid_by: "company_account", payer: null, status: "suggested",
      reasons: [
        { rule: "amount_exact", weight: 0.5, detail: `${formatMoney(doc.totals.gross)} on the invoice and on the card line` },
        { rule: "date_lag", weight: 0.2, detail: "Paid on the day of the invoice" },
        { rule: "name_similarity", weight: 0.25, detail: `${t.counterparty_name_raw ?? "The card line"} is the seller on the invoice` },
      ],
      consequences: { vat_deductible: true, vat_amount: doc.totals.vat ?? null, vat_lost: null, reimbursement_owed: null, note: null },
    } : null;
    uploads.push({ raw, doc, match, readyAt: Date.now() + READ_MS });
    result = raw;
  }
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
    const single = items.filter((a) => a.include_in_liquidity && a.balance).length === 1 ? items.find((a) => a.include_in_liquidity && a.balance)!.balance : null;
    result = { items, total_liquidity_base: forecast?.opening_balance ?? single ?? null };
  } else if (method === "GET" && path === "/transactions") {
    const accountIds = new Set(byCompany(f.accounts, company).map((a) => a.id));
    result = page(f.transactions.filter((t) => accountIds.has(t.account_id) && (!q.get("account_id") || t.account_id === q.get("account_id"))));
  }
  else if (method === "GET" && seg[0] === "transactions" && seg.length === 2) result = find(f.transactions, seg[1]);
  else if (method === "PATCH" && seg[0] === "transactions" && seg.length === 2) {
    const t = find(f.transactions, seg[1]);
    const category = (body as { category?: string } | undefined)?.category ?? t.category;
    categoryEdits.set(t.id, category as Transaction["category"]);
    result = { ...t, category };
  }
  else if (method === "GET" && path === "/counterparties") result = { items: byCompany(f.counterparties, company) };
  else if (method === "GET" && path === "/matches") result = { items: f.matches.filter((m) => !q.get("status") || m.status === q.get("status")) };
  else if (method === "GET" && path === "/inbox") {
    const items = byCompany(f.recommendations, company).filter((r) => r.status === "new" || r.status === "seen");
    result = { items, counts: { approval_required: items.filter((r) => r.control_level === "approval_required").length, recommendation: items.filter((r) => r.control_level === "recommendation").length, analysed_autonomously_today: ACTIVITY.length } };
  } else if (method === "GET" && path === "/ledger") result = page(byCompany(f.ledger, company));
  else if (method === "GET" && path === "/ledger/summary") {
    onlyBorsuk(company, "ledger summary");
    result = { rows: SUMMARY_BY_MONTH[(q.get("from") ?? "2026-10").slice(0, 7)] ?? [], kpis: SUMMARY_KPIS };
  }
  else if (method === "GET" && path === "/balance/history") { onlyBorsuk(company, "balance history"); result = BALANCE_HISTORY; }
  else if (method === "GET" && path === "/people/costs") {
    onlyBorsuk(company, "people costs");
    const month = q.get("month") ?? "2026-10";
    if (month === "2026-10" || month === "2026-09") result = PEOPLE_COSTS;
    else if (month === "2026-11") {
      const items = PEOPLE_COSTS.items.map((p) => ({ ...p, parts: undefined, paid: { amount: p.person_id === "per_piotr" ? "10500.00" : "0.00", currency: "PLN" }, payments: p.person_id === "per_piotr" ? 1 : 0 }))
        .filter((p) => p.paid.amount !== "0.00" || p.owed.amount !== "0.00");
      result = { items, totals: { staff: { amount: "10500.00", currency: "PLN" }, social_security: { amount: "0.00", currency: "PLN" }, share_of_costs: 0.44 } };
    } else result = { items: [], totals: { staff: { amount: "0.00", currency: "PLN" }, social_security: { amount: "0.00", currency: "PLN" }, share_of_costs: 0 } };
  }
  else if (method === "GET" && path === "/clients") { onlyBorsuk(company, "clients"); result = clientsFor(q.get("month") ?? "2026-10"); }
  else if (method === "GET" && path === "/subscriptions") {
    onlyBorsuk(company, "subscriptions");
    if (q.get("scope") === "all") {
      const items = [...SUBSCRIPTIONS.items, ...MONTHLY_EXTRA];
      const total = items.reduce((t, i) => t + BigInt(i.monthly.amount.replace(".", "")), 0n);
      result = { items, monthly_total: { amount: `${total / 100n}.${String(total % 100n).padStart(2, "0")}`, currency: "PLN" } };
    } else result = SUBSCRIPTIONS;
  }
  else if (path === "/settings" && (method === "GET" || method === "PATCH")) {
    onlyBorsuk(company, "settings");
    if (method === "PATCH") {
      const patch = (body ?? {}) as { company?: Partial<Settings["company"]>; alerts?: Partial<Settings["alerts"]> };
      settings = { company: { ...settings.company, ...patch.company }, alerts: { ...settings.alerts, ...patch.alerts } };
    }
    result = settings;
  }
  else if (path === "/people" && method === "GET") { onlyBorsuk(company, "people"); result = { items: people }; }
  else if (path === "/people" && method === "POST") {
    onlyBorsuk(company, "people");
    const added = { ...(body as Omit<Person, "id">), id: `per_new_${people.length + 1}` };
    people = [...people, added];
    result = added;
  }
  else if (seg[0] === "people" && seg.length === 2 && method === "PATCH") {
    onlyBorsuk(company, "people");
    const found = find(people, seg[1]);
    const changed = { ...found, ...(body as Partial<Person>) };
    people = people.map((p) => (p.id === found.id ? changed : p));
    result = changed;
  }
  else if (path === "/rules" && method === "GET") { onlyBorsuk(company, "rules"); result = { items: rules }; }
  else if (seg[0] === "rules" && seg.length === 2 && method === "DELETE") { find(rules, seg[1]); rules = rules.filter((r) => r.id !== seg[1]); result = undefined; }
  else if (method === "GET" && path === "/chat/sessions")
    result = { items: sessions.filter((s) => s.company_id === (company ?? "co_borsuk")).map(({ session_id, title, last_at, messages }) => ({ session_id, title, last_at, messages: messages.length })).sort((a, b) => b.last_at.localeCompare(a.last_at)) };
  else if (method === "GET" && seg[0] === "chat" && seg[1] === "sessions" && seg.length === 3) {
    const s = sessions.find((x) => x.session_id === seg[2]);
    if (!s) throw new MockNotFound(`No chat ${seg[2]}`);
    result = { session_id: s.session_id, messages: s.messages };
  }
  else if (method === "DELETE" && seg[0] === "chat" && seg[1] === "sessions" && seg.length === 3) {
    const s = sessions.find((x) => x.session_id === seg[2] && x.company_id === (company ?? "co_borsuk"));
    if (!s) throw new MockNotFound(`No chat with id ${seg[2]}`);
    sessions = sessions.filter((x) => x !== s);
  }
  else if (seg[0] === "forecast" && (method === "POST" || seg.length === 2)) {
    const forecast = (seg[1] && seg[1] !== "latest" && f.forecasts.find((x) => x.id === seg[1])) || byCompany(f.forecasts, company)[0];
    if (!forecast) throw new MockNotFound(`No forecast fixture for ${company ?? seg[1]}`);
    result = forecast;
  } else if (method === "GET" && path === "/recommendations")
    result = { items: byCompany(f.recommendations, company).filter((r) => (!q.get("status") || r.status === q.get("status")) && (!q.get("agent") || r.agent === q.get("agent")) && (!q.get("control_level") || r.control_level === q.get("control_level"))) };
  else if (method === "GET" && seg[0] === "recommendations" && seg.length === 2) result = find(f.recommendations, seg[1]);
  else if (method === "POST" && seg[0] === "recommendations" && seg[2] === "decision") result = mockDecide(find(allRecommendations(), seg[1]), body as DecisionBody | undefined);
  else if (method === "POST" && seg[0] === "matches" && seg[2] === "decision") {
    const match = find(f.matches, seg[1]);
    const decision = (body as DecisionBody | undefined)?.decision ?? "approved";
    if (decision === "rejected") undoneMatches.add(match.id);
    else {
      confirmedMatches.add(match.id);
      const doc = f.documents.find((d) => d.id === match.document_id);
      if (doc) documentEdits.set(doc.id, { ...doc, status: "approved" });
    }
    result = { ...f.approvals[0], subject_type: "match", subject_id: seg[1], decision, decided_at: demoNow(), changes: null, comment: null, execution: { mode: "none", status: "not_applicable", executed_at: null, reference: null, result: null, effects: [] } };
  } else if (method === "GET" && path === "/approvals") result = { items: [...(company && company !== "co_borsuk" ? [] : SAMPLE_APPROVALS), ...decisions.values()] };
  else if (method === "GET" && path === "/activity") result = { items: (company && company !== "co_borsuk" ? [] : ACTIVITY).filter((a) => !(a.subject?.type === "match" && undoneMatches.has(a.subject.id))) };
  else if (method === "POST" && path === "/chat") {
    const ask = (body ?? {}) as { message?: string; company_id?: string; session_id?: string | null };
    const message = ask.message ?? "";
    const forecast = byCompany(f.forecasts, ask.company_id ?? null)[0] ?? f.forecasts[0];
    const at = demoNow();
    let session = sessions.find((s) => s.session_id === ask.session_id);
    if (!session) {
      session = { session_id: `chat_new_${sessions.length + 1}`, company_id: ask.company_id ?? "co_borsuk", title: message.length > 48 ? `${message.slice(0, 47)}…` : message, last_at: at, messages: [] };
      sessions = [session, ...sessions];
    }
    const { answer, evidence } = mockAnswer(message, forecast);
    session.messages.push({ role: "user", content: message, at }, { role: "assistant", content: answer, at });
    session.last_at = at;
    result = {
      session_id: session.session_id, answer, evidence, table: null,
      tool_calls: [{ tool: "get_forecast", arguments: { horizon_days: forecast.horizon_days }, duration_ms: 12 }], created_recommendation_id: null, guardrail: null, trace_id: null,
    } satisfies ChatAnswer;
  } else if (method === "POST" && path === "/chat/transcribe") {
    const language = (((body ?? {}) as { language?: string }).language ?? "en") as SpeechLanguage;
    if (!(language in HEARD)) throw new MockRefused(422, "language must be one of pl, en, ru");
    await new Promise((done) => setTimeout(done, TRANSCRIBE_MS));
    result = { text: HEARD[language], language, duration_seconds: 2.1, model: "mock", seconds: TRANSCRIBE_MS / 1000 } satisfies Transcript;
  } else if (method === "GET" && path === "/fx/rates") result = f.documents.find((d) => d.totals.fx)?.totals.fx ?? null;
  else if (method === "GET" && path === "/fx/exposure") result = { items: company && company !== "co_borsuk" ? [] : FX_EXPOSURE };
  else throw new MockNotFound(`Mock mode has no handler for ${method} ${path}`);

  return (result === undefined ? undefined : structuredClone(result)) as T;
}

export function mockEventStream(onEvent: (e: OrdoEvent) => void, intervalMs = 1500): () => void {
  const timers = fixtures.events.map((e, i) => setTimeout(() => onEvent(structuredClone(e)), intervalMs * (i + 1)));
  return () => timers.forEach(clearTimeout);
}
