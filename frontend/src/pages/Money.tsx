// Finances: every payment in and out, with the invoice behind it. One place, five ways to look at it.
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type ClientsResponse, type LedgerSummary, type PeopleCosts, type SubscriptionsResponse } from "../api/client";
import type { Recommendation } from "../api/types.gen";
import { Icon } from "../components/Icon";
import { Avatar, Change, Chevron, MonthSelect, PageHead, Skeleton, SlidingTabs, StatusLabel, Tile, Waiting, nth } from "../components/ui";
import { add, costTypes, isZero, monthFigures, monthOnly, percent, previousMonth, recentMonths, subtract, typeOfCategory } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { PAY_LABEL, ROLE_LABEL, categoryLabel, initials, pct, plainName, whole } from "../lib/words";
import { monthAndBefore } from "../lib/monthSummary";
import { FROM_BANK_TEXT, FromBank } from "./Overview";
import { PaymentPanel } from "./money/PaymentPanel";
import { DOC_CHIP, accountShort, buildPayments, filterPayments, typeOf, type Payment } from "./money/payments";

const VIEWS = [
  { key: "", label: "By type" },
  { key: "people", label: "By person" },
  { key: "clients", label: "By client" },
  { key: "monthly", label: "Monthly payments" },
  { key: "payments", label: "All payments" },
] as const;
type View = (typeof VIEWS)[number]["key"];

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

const SEARCH_HINT: Record<View, string> = { "": "Search types", people: "Search people", clients: "Search clients", monthly: "Search monthly payments", payments: "Search payments" };
/** Case-insensitive "contains" over a few texts; an empty search matches everything. */
const matches = (q: string, ...texts: (string | null | undefined)[]) => !q.trim() || texts.some((t) => t?.toLowerCase().includes(q.trim().toLowerCase()));
const NoMatch = ({ q }: { q: string }) => <p className="t2" style={{ padding: 12 }}>Nothing matches “{q.trim()}”.</p>;

export function Money() {
  const { view = "", id } = useParams();
  const [params, setParams] = useSearchParams();
  const today = useToday();
  // Old links to Subscriptions open Monthly payments.
  const v = (view === "subscriptions" ? "monthly" : VIEWS.some((x) => x.key === view) ? view : "") as View;
  // Every view opens on the current month (All payments on all months when it is asked for a kind of payment or a
  // name). "" means all months.
  const asked = params.get("month");
  const month = v === "payments" ? (asked ?? (params.get("doc") || params.get("q") ? "" : today.slice(0, 7))) : (asked || today.slice(0, 7));
  const q = params.get("q") ?? "";
  const keep = (key: string) => `/money${key ? `/${key}` : ""}${params.get("month") ? `?month=${month}` : ""}`;

  function setMonth(m: string) { params.set("month", m); setParams(params); }
  function search(text: string) {
    const p = new URLSearchParams(params);
    if (text) p.set("q", text); else p.delete("q");
    setParams(p, { replace: true });
  }
  return (
    <>
      <PageHead title="Finances" sub="Every payment in and out, with the invoice behind it." />
      <div className="toolbar">
        <MonthSelect value={month} months={recentMonths(today, 12)} onChange={setMonth} allowAll={v === "payments"} />
        <SlidingTabs label="Views" active={v} items={VIEWS.map((x) => ({ key: x.key, label: x.label, to: keep(x.key) }))} />
        <span className="grow" />
        <form className="search" role="search" onSubmit={(e: FormEvent<HTMLFormElement>) => e.preventDefault()}>
          <Icon name="search" size={14} />
          <input type="search" name="q" placeholder={SEARCH_HINT[v]} value={q} aria-label={SEARCH_HINT[v]} onChange={(e) => search(e.target.value)} />
        </form>
      </div>
      {v === "" && <ByType month={month} q={q} />}
      {v === "people" && <ByPerson month={month} q={q} />}
      {v === "clients" && <ByClient month={month} q={q} />}
      {v === "monthly" && <Monthly month={month} q={q} />}
      {v === "payments" && <AllPayments month={month} selected={id ?? null} />}
    </>
  );
}

// ---- By type ----
function ByType({ month, q }: { month: string; q: string }) {
  const { companyId } = useCompany();
  const currency = useCompanyInfo()?.base_currency ?? "PLN";
  const refresh = useRefreshKey();
  const state = useApi(() => monthAndBefore(companyId, month), [companyId, month, refresh]);
  if (state.loading && !state.data) return <Skeleton tiles={3} rows={6} />;
  const [current, before] = state.data ?? [null, null];
  if (!current) return <Waiting what="costs by type" />;
  return <ByTypeView month={month} summary={current.summary} fromBank={current.fromBank} before={before} currency={currency} q={q} />;
}

export function ByTypeView({ month, summary, fromBank, before, currency, q = "" }: { month: string; summary: LedgerSummary; fromBank?: boolean; before: LedgerSummary | null; currency: string; q?: string }) {
  const f = monthFigures(summary, currency);
  const prev = before?.rows.length ? monthFigures(before, currency) : null;
  const entries = (cats: string[]) => summary.rows.filter((r) => cats.includes(r.key)).reduce((n, r) => n + r.entries, 0);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) => setOpen((o) => { const n = new Set(o); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const types = f.types.filter((t) => matches(q, t.type.label, t.type.tag, ...t.categories.map((c) => categoryLabel(c.key))));
  if (!f.hasData) return <p className="t2">No payments in {monthOnly(month)}.</p>;
  return (
    <>
      {fromBank && <div className="hstack"><FromBank /><span className="small t2">{FROM_BANK_TEXT}</span></div>}
      <div className="row">
        <Tile label={`Costs in ${monthOnly(month)}`} value={whole(f.costs)} note={prev && <Change now={f.costs} before={prev.costs} upIsGood={false} vs={monthOnly(previousMonth(month))} />} />
        <Tile label="Fixed every month" value={whole(f.fixed)} note={`${percent(f.fixed.amount, f.costs.amount)}% of all costs`} />
        <Tile label="Not explained yet" value={whole(f.unexplained)} note={`${entries(["other"])} payments without a type`} tone={isZero(f.unexplained.amount) ? undefined : "warn"}
          to={`/money/payments?month=${month}&type=unexplained`} />
      </div>
      <div className="card table">
        <div className="trow head"><span className="cell grow">Type</span><span className="cell" style={{ width: 120 }}>Repeats</span><span className="cell r" style={{ width: 90 }}>Payments</span><span className="cell r" style={{ width: 140 }}>{monthOnly(month)}</span><span className="cell r" style={{ width: 70 }}>Share</span><span style={{ width: 16 }} /></div>
        {types.length === 0 && <NoMatch q={q} />}
        {types.map((t, i) => {
          const isOpen = open.has(t.type.key) || (q.trim() !== "" && !matches(q, t.type.label, t.type.tag));
          return (
            <div key={t.type.key} className="group" style={nth(i)}>
              <button type="button" className="trow group-head" aria-expanded={isOpen} onClick={() => toggle(t.type.key)}>
                <span className="cell col grow">
                  <span className="hstack" style={{ gap: 8 }}><span className="dot" style={{ background: t.type.color }} /><span className="medium">{t.type.label}</span></span>
                  <span className="caption t3">{t.categories.map((c) => categoryLabel(c.key)).join(", ")}</span>
                </span>
                <span className="cell small t2" style={{ width: 120 }}>{t.type.tag}</span>
                <span className="cell r t2" style={{ width: 90 }}>{entries(t.type.categories)}</span>
                <span className="cell r" style={{ width: 140 }}>{whole(t.amount)}</span>
                <span className="cell r t2" style={{ width: 70 }}>{percent(t.amount.amount, f.costs.amount)}%</span>
                <span className={`chev${isOpen ? " open" : ""}`} aria-hidden="true"><Icon name="chevronRight" size={16} /></span>
              </button>
              {isOpen && (
                <>
                  {t.categories.map((c) => (
                    <div key={c.key} className="trow sub">
                      <span className="cell grow small">{categoryLabel(c.key)}</span>
                      <span className="cell r t2 small" style={{ width: 90 }}>{entries([c.key])}</span>
                      <span className="cell r small" style={{ width: 140 }}>{whole(c.amount)}</span>
                      <span className="cell r t2 small" style={{ width: 70 }}>{percent(c.amount.amount, f.costs.amount)}%</span>
                      <span style={{ width: 16 }} />
                    </div>
                  ))}
                  <div className="trow sub"><Link to={`/money/payments?month=${month}&type=${t.type.key}`} className="small">See the {entries(t.type.categories)} payments</Link></div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ---- By person ----
function ByPerson({ month, q }: { month: string; q: string }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => api.peopleCosts(companyId, month).catch(() => null), [companyId, month, refresh]);
  if (state.loading && !state.data) return <Skeleton tiles={3} rows={6} />;
  if (!state.data) return <Waiting what="costs per person" />;
  return <ByPersonView month={month} data={state.data} q={q} />;
}

export function ByPersonView({ month, data, q = "" }: { month: string; data: PeopleCosts; q?: string }) {
  const people = data.items.filter((p) => matches(q, plainName(p.name), ROLE_LABEL[p.role] ?? p.role, PAY_LABEL[p.pay_type ?? ""]));
  const owed = data.items.reduce((s, p) => add(s, p.owed.amount), "0.00");
  const receipts = data.items.reduce((n, p) => n + p.receipts_owed, 0);
  const currency = data.totals.staff.currency;
  const roles = ["owner", "employee", "contractor"].map((r) => [r, data.items.filter((p) => p.role === r).length] as const).filter(([, n]) => n > 0)
    .map(([r, n]) => (r === "owner" ? "Owner" : `${n} ${r}${n === 1 ? "" : "s"}`)).join(", ");
  if (data.items.length === 0) return <p className="t2">No staff costs booked in {monthOnly(month)} yet.</p>;
  return (
    <>
      <div className="row">
        <Tile label={`Staff cost in ${monthOnly(month)}`} value={whole(data.totals.staff)} note={`${pct(data.totals.share_of_costs)} of all costs`} />
        <Tile label="Owed to the team" value={whole({ amount: owed, currency })} note={receipts ? `${receipts} receipts paid with their own cards` : "Nothing to pay back"} tone={receipts ? "warn" : undefined} />
        <Tile label="People" value={data.items.length} note={roles} />
      </div>
      <div className="card table">
        <div className="trow head"><span className="cell grow">Person</span><span className="cell" style={{ width: 140 }}>How we pay</span><span className="cell r" style={{ width: 260 }}>Cost in {monthOnly(month)}</span><span className="cell r" style={{ width: 120 }}>Owed to them</span><span style={{ width: 16 }} /></div>
        {people.length === 0 && <NoMatch q={q} />}
        {people.map((p, i) => (
          <Link style={nth(i)} key={p.person_id} to={`/money/payments?month=${month}&q=${encodeURIComponent(plainName(p.name).split(" ").at(-1) ?? "")}`} className="trow">
            <span className="cell grow" style={{ gap: 12 }}>
              <Avatar text={initials(p.name)} />
              <span className="stack" style={{ gap: 0 }}><span>{plainName(p.name)}</span><span className="caption t3">{ROLE_LABEL[p.role] ?? p.role}</span></span>
            </span>
            <span className="cell" style={{ width: 140 }}>{PAY_LABEL[p.pay_type ?? ""] ?? "—"}</span>
            <span className="cell col r" style={{ width: 260 }}>
              <span>{whole(p.paid)}</span>
              {p.parts?.length ? <span className="caption t3">{p.parts.map((x) => `${whole(x.amount).replace(` ${x.amount.currency}`, "")} ${x.label}`).join(" + ")}</span>
                : p.pay_type === "invoice" && !isZero(p.paid.amount) ? <span className="caption t3">Invoice for {monthOnly(month)}</span> : null}
            </span>
            <span className="cell r" style={{ width: 120 }}>{isZero(p.owed.amount) ? <span className="t3">—</span> : <span className="chip warn">{whole(p.owed)}</span>}</span>
            <Chevron />
          </Link>
        ))}
      </div>
    </>
  );
}

// ---- By client ----
function ByClient({ month, q }: { month: string; q: string }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => Promise.all([none(api.clients(companyId, month)), none(api.inbox(companyId))]), [companyId, month, refresh]);
  if (state.loading && !state.data) return <Skeleton tiles={3} rows={6} />;
  const [clients, inbox] = state.data ?? [null, null];
  if (!clients) return <Waiting what="clients and what they owe" />;
  return <ByClientView month={month} data={clients} q={q} fx={inbox?.items.filter((r) => r.agent === "fx" && r.control_level === "approval_required") ?? []} />;
}

export function ByClientView({ month, data, fx, q = "" }: { month: string; data: ClientsResponse; fx: Recommendation[]; q?: string }) {
  const clients = data.items.filter((c) => matches(q, plainName(c.name), c.currency, ...c.open_invoices.map((i) => i.number)));
  const biggest = [...data.items].sort((a, b) => b.share_of_income - a.share_of_income)[0];
  return (
    <>
      <div className="row">
        <Tile label={`Paid in ${monthOnly(month)}`} value={whole(data.totals.paid_in_month)} note={`${data.items.filter((c) => !isZero(c.paid_in_month.amount)).length} clients paid`} />
        <Tile label="Clients still owe you" value={whole(data.totals.open_base)} note={isZero(data.totals.late_base.amount) ? "Nothing is late" : `${whole(data.totals.late_base)} of it is late`} tone={isZero(data.totals.late_base.amount) ? undefined : "bad"} />
        <Tile label="Biggest client" value={biggest && biggest.share_of_income > 0 ? plainName(biggest.name).split(" ")[0] : "—"} note={biggest && biggest.share_of_income > 0 ? `${pct(biggest.share_of_income)} of ${monthOnly(month)} income` : "No client paid this month"} />
      </div>
      <div className="card table">
        <div className="trow head"><span className="cell grow">Client</span><span className="cell r" style={{ width: 150 }}>Paid in {monthOnly(month)}</span><span className="cell r" style={{ width: 200 }}>Still owes</span><span className="cell r" style={{ width: 120 }}>Status</span><span style={{ width: 16 }} /></div>
        {clients.length === 0 && <NoMatch q={q} />}
        {clients.map((c, i) => {
          const late = Math.max(0, ...c.open_invoices.map((i) => i.days_late));
          const due = c.open_invoices.map((i) => i.due_date).filter((d): d is string => Boolean(d)).sort()[0];
          const one = c.open_invoices.length === 1 ? c.open_invoices[0] : null;
          const habit = c.typical_payment_delay_days === null ? `New client${c.currency !== data.totals.open_base.currency ? ` · pays in ${c.currency}` : ""}`
            : c.typical_payment_delay_days <= 1 ? "Usually pays on time" : `Usually pays ${c.typical_payment_delay_days} days late`;
          return (
            <Link style={nth(i)} key={c.counterparty_id} to={`/money/payments?month=${month}&q=${encodeURIComponent(plainName(c.name).split(" ")[0])}`} className="trow">
              <span className="cell col grow"><span>{plainName(c.name)}</span><span className="caption t3">{habit}</span></span>
              <span className="cell r" style={{ width: 150 }}>{isZero(c.paid_in_month.amount) ? <span className="t3">—</span> : whole(c.paid_in_month)}</span>
              <span className="cell col r" style={{ width: 200 }}>
                {one ? <><span>{whole(one.gross)}</span><span className="caption t3">{one.gross.currency !== one.gross_base.currency ? `about ${whole(one.gross_base)}` : `invoice ${one.number ?? ""}`}</span></>
                  : c.open_invoices.length ? <><span>{whole(c.open_total_base)}</span><span className="caption t3">{c.open_invoices.length} invoices</span></> : <span className="t3">—</span>}
              </span>
              <span className="cell r" style={{ width: 120 }}>
                {late > 0 ? <span className={`chip ${late >= 7 ? "bad" : "warn"}`}>{late} days late</span> : due ? <span className="chip neutral">Due {shortDate(due)}</span> : null}
              </span>
              <Chevron />
            </Link>
          );
        })}
      </div>
      {fx.map((r) => (
        <div key={r.id} className="card hstack" style={{ gap: 24, flexWrap: "nowrap" }}>
          <div className="stack grow" style={{ gap: 6 }}>
            <span className="chip info" style={{ alignSelf: "flex-start" }}>Currency risk</span>
            <span className="medium">{r.title}</span>
            <span className="small t2 clamp2">{r.summary}</span>
          </div>
          <Link to={`/todo#${r.id}`} className="button">See it in To-do</Link>
        </div>
      ))}
    </>
  );
}

// ---- Subscriptions ----
function Monthly({ month, q }: { month: string; q: string }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => api.subscriptions(companyId, month, "all").catch(() => null), [companyId, month, refresh]);
  if (state.loading && !state.data) return <Skeleton tiles={3} rows={6} />;
  if (!state.data) return <Waiting what="monthly payments" />;
  return <MonthlyView data={state.data} month={month} q={q} />;
}

/** Two names and how many more, so a tile stays one line or two. */
const worthALook = (notes: string[]): string =>
  notes.length === 0 ? "No price rises, nothing paid twice" : notes.slice(0, 2).join(" · ") + (notes.length > 2 ? ` and ${notes.length - 2} more` : "");

/** Everything paid every month, grouped by type; each type opens to its payments. */
export function MonthlyView({ data, month, q = "" }: { data: SubscriptionsResponse; month: string; q?: string }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const twice = data.items.filter((s) => s.flags.includes("paid_twice"));
  const up = data.items.filter((s) => s.flags.includes("price_up"));
  const notYet = data.items.filter((s) => s.paid_in_month === false);
  const currency = data.monthly_total.currency;
  const sum = (items: typeof data.items) => whole({ amount: items.reduce((t, x) => add(t, x.monthly.amount), "0.00"), currency });
  const rise = (s: (typeof data.items)[number]) => (s.previous_monthly && !isZero(s.previous_monthly.amount) ? `+${percent(subtract(s.monthly.amount, s.previous_monthly.amount), s.previous_monthly.amount)}%` : null);
  const FLAG: Record<string, [string, string]> = { paid_twice: ["Paid twice", "bad"], paid_privately: ["Paid privately", "warn"] };
  const found = data.items.filter((s) => matches(q, plainName(s.name), categoryLabel(s.category), typeOfCategory(s.category).label, ...s.paid_by.map((x) => x.label)));
  const groups = costTypes().map((t) => ({ type: t, items: found.filter((s) => typeOfCategory(s.category).key === t.key) })).filter((g) => g.items.length);
  const toggle = (key: string) => setOpen((o) => { const n = new Set(o); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  if (data.items.length === 0) return <p className="t2">Nothing repeats every month yet.</p>;
  return (
    <>
      <div className="row">
        <Tile label="Every month" value={whole(data.monthly_total)} note={`${data.items.length} payments that repeat`} />
        <Tile label={`Not paid yet in ${monthOnly(month)}`} value={notYet.length ? sum(notYet) : "Nothing"} note={notYet.length ? `${notYet.length} payments still to come` : "Everything is paid"} tone={notYet.length ? "warn" : undefined} />
        <Tile label="Worth a look" value={`${twice.length + up.length}`}
          note={worthALook([...twice.map((s) => `${plainName(s.name)} paid twice`), ...up.map((s) => [plainName(s.name), rise(s)].filter(Boolean).join(" "))])}
          tone={twice.length + up.length ? "warn" : undefined} />
      </div>
      <div className="card table">
        {groups.length === 0 && <NoMatch q={q} />}
        {groups.map((g) => {
          const isOpen = open.has(g.type.key) || q.trim() !== "";
          return (
            <div key={g.type.key} className="group">
              <button type="button" className="trow group-head" aria-expanded={isOpen} onClick={() => toggle(g.type.key)}>
                <span className="cell grow" style={{ gap: 8 }}><span className="dot" style={{ background: g.type.color }} /><span className="medium">{g.type.label}</span>
                  <span className="small t3">{g.items.length} payment{g.items.length === 1 ? "" : "s"}</span></span>
                <span className="cell r" style={{ width: 160 }}>{sum(g.items)}</span>
                <span className={`chev${isOpen ? " open" : ""}`} aria-hidden="true"><Icon name="chevronRight" size={16} /></span>
              </button>
              {isOpen && g.items.map((s, i) => (
                <Link style={nth(i)} key={s.counterparty_id} to={`/money/payments?q=${encodeURIComponent(plainName(s.name).split(" ")[0])}`} className="trow sub">
                  <span className="cell col grow"><span>{plainName(s.name)}</span><span className="caption t3">{categoryLabel(s.category)} · {s.paid_by.map((x) => x.label).join(" and ")}</span></span>
                  <span className="cell r" style={{ width: 130 }}>
                    {s.paid_in_month === false ? <span className="chip neutral">Not paid yet</span>
                      : s.flags.includes("price_up") ? <span className="chip warn">{rise(s) ? `${rise(s)} lately` : "Price went up"}</span>
                      : s.flags.map((fl) => FLAG[fl]).filter(Boolean).slice(0, 1).map(([text, tone]) => <span key={text} className={`chip ${tone}`}>{text}</span>)}
                  </span>
                  <span className="cell col r" style={{ width: 160 }}><span>{whole(s.monthly)}</span>{s.original && <span className="caption t3">{formatMoney(s.original).replace(".00 ", " ")}</span>}</span>
                  <Chevron />
                </Link>
              ))}
            </div>
          );
        })}
      </div>
      {twice.map((s) => (
        <div key={s.counterparty_id} className="card hstack" style={{ gap: 16 }}>
          <StatusLabel level="recommendation" />
          <span>{plainName(s.name)} is paid by {s.paid_by.length} people. One plan is enough{s.duplicate_cost ? `, which saves ${whole(s.duplicate_cost)} a month` : ""}.</span>
        </div>
      ))}
    </>
  );
}

// ---- All payments ----
const PAGE = 25;

function AllPayments({ month, selected }: { month: string; selected: string | null }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const [reload, setReload] = useState(0);
  const state = useApi(() => Promise.all([
    api.transactions(companyId), api.accounts(companyId), none(api.counterparties(companyId)), none(api.matches(companyId)), none(api.documents(companyId)),
  ]), [companyId, refresh, reload]);
  if (state.loading && !state.data) return <Skeleton tiles={3} rows={6} />;
  if (state.error) return <p className="bad" role="alert">Could not load the payments: {state.error}</p>;
  const [transactions, accounts, counterparties, matches, documents] = state.data!;
  const all = buildPayments({ transactions: transactions.items, accounts: accounts.items, counterparties: counterparties?.items ?? [], matches: matches?.items ?? [], documents: documents?.items ?? [] });
  return <PaymentsView all={all} month={month} selected={selected} onChanged={() => setReload((n) => n + 1)} />;
}

export function PaymentsView({ all, month, selected, onChanged }: { all: Payment[]; month: string; selected: string | null; onChanged: () => void }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [shown, setShown] = useState(PAGE);
  const filter = { month, type: params.get("type"), doc: params.get("doc"), q: params.get("q"), account: params.get("account") };
  const accounts = [...new Map(all.filter((p) => p.account).map((p) => [p.account!.id, p.account!])).values()];
  function setAccount(id: string) { const p = new URLSearchParams(params); if (id) p.set("account", id); else p.delete("account"); navigate(`/money/payments${selected ? `/${selected}` : ""}${p.toString() ? `?${p}` : ""}`); }
  const list = filterPayments(all, filter);
  const open = all.find((p) => p.id === selected) ?? null;
  const qs = params.toString() ? `?${params}` : "";
  const drop = (key: string) => { const p = new URLSearchParams(params); p.delete(key); navigate(`/money/payments${selected ? `/${selected}` : ""}${p.toString() ? `?${p}` : ""}`); };
  const typeName = filter.type ? (list[0] ? typeOf(list[0]).label : filter.type) : null;
  return (
    <div className="hstack" style={{ alignItems: "flex-start", gap: 24, flexWrap: "nowrap" }}>
      <div className="stack grow" style={{ gap: 12 }}>
        <div className="hstack">
          <label className="pill-select">
            <span className="pill-label">{filter.account ? (filter.account === "private" ? "Paid privately" : accountShort(accounts.find((a) => a.id === filter.account) ?? null)) : "All accounts"}</span>
            <select aria-label="Account" value={filter.account ?? ""} onChange={(e) => setAccount(e.target.value)}>
              <option value="">All accounts</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>{accountShort(a)}</option>)}
              {all.some((p) => !p.account) && <option value="private">Paid privately</option>}
            </select>
            <Icon name="chevron" size={14} />
          </label>
        {(filter.type || filter.doc || filter.q) && (
          <>
            {filter.type && <button type="button" className="chip" onClick={() => drop("type")}>{typeName} ✕</button>}
            {filter.doc && <button type="button" className="chip" onClick={() => drop("doc")}>{filter.doc === "missing" ? "No invoice" : DOC_CHIP[filter.doc as keyof typeof DOC_CHIP]?.text ?? filter.doc} ✕</button>}
            {filter.q && <button type="button" className="chip" onClick={() => drop("q")}>“{filter.q}” ✕</button>}
          </>
        )}
        </div>
        <div className="card table">
          <div className="trow head">
            <span className="cell" style={{ width: 56 }}>Date</span><span className="cell grow">To / From</span><span className="cell" style={{ width: 150 }}>Account</span>
            <span className="cell" style={{ width: 96 }}>Document</span><span className="cell r" style={{ width: 130 }}>Amount</span>
          </div>
          {list.length === 0 && <p className="t2" style={{ padding: 12 }}>No payments match{month ? ` in ${monthOnly(month)}` : ""}.</p>}
          {list.slice(0, shown).map((p, i) => {
            const t = typeOf(p);
            const chip = DOC_CHIP[p.doc];
            return (
              <Link style={nth(i)} key={p.id} to={`/money/payments/${p.id}${qs}`} className={`trow${p.id === selected ? " selected" : ""}`}>
                <span className="cell small t2" style={{ width: 56 }}>{p.date ? shortDate(p.date) : "—"}</span>
                <span className="cell col grow"><span className="ellipsis" title={p.name}>{p.name}</span><span className="caption t3 hstack" style={{ gap: 6 }}><span className="dot" style={{ background: t.color }} />{t.label}</span></span>
                <span className="cell small t2 ellipsis" style={{ width: 150 }} title={p.paidBy}>{p.paidBy}</span>
                <span className="cell" style={{ width: 96 }}><span className={`chip ${chip.tone}`}>{chip.text}</span></span>
                <span className={`cell r nowrap${p.amount.amount.startsWith("-") ? "" : " good"}`} style={{ width: 130 }}>{p.amount.amount.startsWith("-") ? "" : "+"}{formatMoney(p.amount)}</span>
              </Link>
            );
          })}
        </div>
        <div className="hstack">
          <span className="small t3">Showing {Math.min(shown, list.length)} of {list.length}</span>
          <span className="grow" />
          {shown < list.length && <button type="button" className="quiet" onClick={() => setShown(shown + PAGE)}>Show more</button>}
        </div>
      </div>
      {open && <PaymentPanel key={open.id} payment={open} onClose={() => navigate(`/money/payments${qs}`)} onChanged={onChanged} />}
    </div>
  );
}
