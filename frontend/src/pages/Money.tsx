// Money: every payment in and out, with the invoice behind it. One place, five ways to look at it.
import { useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type ClientsResponse, type LedgerSummary, type PeopleCosts, type SubscriptionsResponse } from "../api/client";
import type { Recommendation } from "../api/types.gen";
import { Icon } from "../components/Icon";
import { Avatar, Change, Chevron, MonthSelect, PageHead, StatusLabel, Tile, Waiting } from "../components/ui";
import { add, isZero, lastFullMonth, monthFigures, monthOnly, monthRange, percent, previousMonth, recentMonths, subtract } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { PAY_LABEL, ROLE_LABEL, categoryLabel, initials, pct, plainName, whole } from "../lib/words";
import { PaymentPanel } from "./money/PaymentPanel";
import { DOC_CHIP, buildPayments, filterPayments, typeOf, type Payment } from "./money/payments";

const VIEWS = [
  { key: "", label: "By type" },
  { key: "people", label: "By person" },
  { key: "clients", label: "By client" },
  { key: "subscriptions", label: "Subscriptions" },
  { key: "payments", label: "All payments" },
] as const;
type View = (typeof VIEWS)[number]["key"];

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

export function Money() {
  const { view = "", id } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const today = useToday();
  const v = (VIEWS.some((x) => x.key === view) ? view : "") as View;
  // All payments starts on this month (or on all months when it is asked for a kind of payment or a name);
  // the summaries on the last full month. "" means all months.
  const asked = params.get("month");
  const month = v === "payments" ? (asked ?? (params.get("doc") || params.get("q") ? "" : today.slice(0, 7))) : (asked || lastFullMonth(today));
  const q = params.get("q") ?? "";
  const keep = (key: string) => `/money${key ? `/${key}` : ""}${params.get("month") ? `?month=${month}` : ""}`;

  function setMonth(m: string) { params.set("month", m); setParams(params); }
  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = String(new FormData(e.currentTarget).get("q") ?? "").trim();
    const p = new URLSearchParams(month ? { month } : {});
    if (text) p.set("q", text);
    navigate(`/money/payments?${p}`);
  }
  return (
    <>
      <PageHead title="Money" sub="Every payment in and out, with the invoice behind it." />
      <div className="toolbar">
        {v !== "subscriptions" && <MonthSelect value={month} months={recentMonths(today, 12)} onChange={setMonth} allowAll={v === "payments"} />}
        <nav className="tabs" aria-label="Views">
          {VIEWS.map((x) => <NavLink key={x.key} to={keep(x.key)} end className={() => (x.key === v ? "on" : "")}>{x.label}</NavLink>)}
        </nav>
        <span className="grow" />
        <form className="search" role="search" onSubmit={search}>
          <Icon name="search" size={14} />
          <input key={q} type="search" name="q" placeholder="Search payments" defaultValue={q} aria-label="Search payments"
            onChange={(e) => { if (v === "payments") { if (e.target.value) params.set("q", e.target.value); else params.delete("q"); setParams(params, { replace: true }); } }} />
        </form>
      </div>
      {v === "" && <ByType month={month} />}
      {v === "people" && <ByPerson month={month} />}
      {v === "clients" && <ByClient month={month} />}
      {v === "subscriptions" && <Subscriptions />}
      {v === "payments" && <AllPayments month={month} selected={id ?? null} />}
    </>
  );
}

// ---- By type ----
function ByType({ month }: { month: string }) {
  const { companyId } = useCompany();
  const currency = useCompanyInfo()?.base_currency ?? "PLN";
  const refresh = useRefreshKey();
  const state = useApi(() => Promise.all([
    none(api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month) })),
    none(api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(previousMonth(month)) })),
  ]), [companyId, month, refresh]);
  if (state.loading && !state.data) return <p className="t3">Loading…</p>;
  const [summary, before] = state.data ?? [null, null];
  if (!summary) return <Waiting what="costs by type" />;
  return <ByTypeView month={month} summary={summary} before={before} currency={currency} />;
}

export function ByTypeView({ month, summary, before, currency }: { month: string; summary: LedgerSummary; before: LedgerSummary | null; currency: string }) {
  const f = monthFigures(summary, currency);
  const prev = before?.rows.length ? monthFigures(before, currency) : null;
  const entries = (cats: string[]) => summary.rows.filter((r) => cats.includes(r.key)).reduce((n, r) => n + r.entries, 0);
  if (!f.hasData) return <p className="t2">Nothing was booked in {monthOnly(month)}.</p>;
  return (
    <>
      <div className="row">
        <Tile label={`Costs in ${monthOnly(month)}`} value={whole(f.costs)} note={prev && <Change now={f.costs} before={prev.costs} upIsGood={false} vs={monthOnly(previousMonth(month))} />} />
        <Tile label="Fixed every month" value={whole(f.fixed)} note={`${percent(f.fixed.amount, f.costs.amount)}% of all costs`} />
        <Tile label="Not explained yet" value={whole(f.unexplained)} note={`${entries(["other"])} payments without a type`} tone={isZero(f.unexplained.amount) ? undefined : "warn"}
          to={`/money/payments?month=${month}&type=unexplained`} />
      </div>
      <div className="card table">
        <div className="trow head"><span className="cell grow">Type</span><span className="cell" style={{ width: 120 }}>Repeats</span><span className="cell r" style={{ width: 90 }}>Payments</span><span className="cell r" style={{ width: 140 }}>{monthOnly(month)}</span><span className="cell r" style={{ width: 70 }}>Share</span><span style={{ width: 16 }} /></div>
        {f.types.map((t) => (
          <Link key={t.type.key} to={`/money/payments?month=${month}&type=${t.type.key}`} className="trow">
            <span className="cell col grow">
              <span className="hstack" style={{ gap: 8 }}><span className="dot" style={{ background: t.type.color }} />{t.type.label}</span>
              <span className="caption t3">{t.categories.map((c) => categoryLabel(c.key)).join(", ")}</span>
            </span>
            <span className="cell small t2" style={{ width: 120 }}>{t.type.tag}</span>
            <span className="cell r t2" style={{ width: 90 }}>{entries(t.type.categories)}</span>
            <span className="cell r" style={{ width: 140 }}>{whole(t.amount)}</span>
            <span className="cell r t2" style={{ width: 70 }}>{percent(t.amount.amount, f.costs.amount)}%</span>
            <Chevron />
          </Link>
        ))}
      </div>
    </>
  );
}

// ---- By person ----
function ByPerson({ month }: { month: string }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => api.peopleCosts(companyId, month).catch(() => null), [companyId, month, refresh]);
  if (state.loading && !state.data) return <p className="t3">Loading…</p>;
  if (!state.data) return <Waiting what="costs per person" />;
  return <ByPersonView month={month} data={state.data} />;
}

export function ByPersonView({ month, data }: { month: string; data: PeopleCosts }) {
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
        {data.items.map((p) => (
          <Link key={p.person_id} to={`/money/payments?month=${month}&q=${encodeURIComponent(plainName(p.name).split(" ").at(-1) ?? "")}`} className="trow">
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
function ByClient({ month }: { month: string }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => Promise.all([none(api.clients(companyId, month)), none(api.inbox(companyId))]), [companyId, month, refresh]);
  if (state.loading && !state.data) return <p className="t3">Loading…</p>;
  const [clients, inbox] = state.data ?? [null, null];
  if (!clients) return <Waiting what="clients and what they owe" />;
  return <ByClientView month={month} data={clients} fx={inbox?.items.filter((r) => r.agent === "fx" && r.control_level === "approval_required") ?? []} />;
}

export function ByClientView({ month, data, fx }: { month: string; data: ClientsResponse; fx: Recommendation[] }) {
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
        {data.items.map((c) => {
          const late = Math.max(0, ...c.open_invoices.map((i) => i.days_late));
          const due = c.open_invoices.map((i) => i.due_date).filter((d): d is string => Boolean(d)).sort()[0];
          const one = c.open_invoices.length === 1 ? c.open_invoices[0] : null;
          const habit = c.typical_payment_delay_days === null ? `New client${c.currency !== data.totals.open_base.currency ? ` · pays in ${c.currency}` : ""}`
            : c.typical_payment_delay_days <= 1 ? "Usually pays on time" : `Usually pays ${c.typical_payment_delay_days} days late`;
          return (
            <Link key={c.counterparty_id} to={`/money/payments?month=${month}&q=${encodeURIComponent(plainName(c.name).split(" ")[0])}`} className="trow">
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
function Subscriptions() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const state = useApi(() => api.subscriptions(companyId).catch(() => null), [companyId, refresh]);
  if (state.loading && !state.data) return <p className="t3">Loading…</p>;
  if (!state.data) return <Waiting what="subscriptions" />;
  return <SubscriptionsView data={state.data} />;
}

export function SubscriptionsView({ data }: { data: SubscriptionsResponse }) {
  const twice = data.items.filter((s) => s.flags.includes("paid_twice"));
  const up = data.items.filter((s) => s.flags.includes("price_up"));
  const saving = twice.reduce((s, x) => (x.duplicate_cost ? add(s, x.duplicate_cost.amount) : s), "0.00");
  const currency = data.monthly_total.currency;
  const rise = (s: (typeof data.items)[number]) => (s.previous_monthly && !isZero(s.previous_monthly.amount) ? `+${percent(subtract(s.monthly.amount, s.previous_monthly.amount), s.previous_monthly.amount)}%` : null);
  const FLAG: Record<string, [string, string]> = { paid_twice: ["Paid twice", "bad"], paid_privately: ["Paid privately", "warn"] };
  return (
    <>
      <div className="row">
        <Tile label="Every month" value={whole(data.monthly_total)} note={`${data.items.length} tools and services`} />
        <Tile label="Paid twice" value={twice.length ? (isZero(saving) ? `${twice.length} tools` : whole({ amount: saving, currency })) : "None"}
          note={twice.length ? twice.map((s) => `${plainName(s.name)}, by ${s.paid_by.map((p) => p.label.replace(/'s card$/, "")).join(" and ")}`).join("; ") : "Every tool is paid once"} tone={twice.length ? "bad" : undefined} />
        <Tile label="Price went up" value={up.length ? `${up.length} tool${up.length === 1 ? "" : "s"}` : "None"} note={up.length ? up.map((s) => [plainName(s.name), rise(s)].filter(Boolean).join(", ")).join("; ") : "No price changes"} tone={up.length ? "warn" : undefined} />
      </div>
      <div className="card table">
        <div className="trow head"><span className="cell grow">Tool</span><span className="cell" style={{ width: 240 }}>Paid by</span><span className="cell r" style={{ width: 130 }}>Every month</span><span className="cell r" style={{ width: 130 }} /><span style={{ width: 16 }} /></div>
        {data.items.map((s) => (
          <Link key={s.counterparty_id} to={`/money/payments?q=${encodeURIComponent(plainName(s.name).split(" ")[0])}`} className="trow">
            <span className="cell col grow"><span>{plainName(s.name)}</span><span className="caption t3">{categoryLabel(s.category)}</span></span>
            <span className="cell small t2" style={{ width: 240 }}>{s.paid_by.map((p) => p.label).join(" and ")}</span>
            <span className="cell col r" style={{ width: 130 }}><span>{whole(s.monthly)}</span>{s.original && <span className="caption t3">{formatMoney(s.original).replace(".00 ", " ")}</span>}</span>
            <span className="cell r" style={{ width: 130 }}>
              {s.flags.includes("price_up") ? <span className="chip warn">{rise(s) ? `${rise(s)} lately` : "Price went up"}</span>
                : s.flags.map((fl) => FLAG[fl]).filter(Boolean).slice(0, 1).map(([text, tone]) => <span key={text} className={`chip ${tone}`}>{text}</span>)}
            </span>
            <Chevron />
          </Link>
        ))}
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
  if (state.loading && !state.data) return <p className="t3">Loading…</p>;
  if (state.error) return <p className="bad" role="alert">Could not load the payments: {state.error}</p>;
  const [transactions, accounts, counterparties, matches, documents] = state.data!;
  const all = buildPayments({ transactions: transactions.items, accounts: accounts.items, counterparties: counterparties?.items ?? [], matches: matches?.items ?? [], documents: documents?.items ?? [] });
  return <PaymentsView all={all} month={month} selected={selected} onChanged={() => setReload((n) => n + 1)} />;
}

export function PaymentsView({ all, month, selected, onChanged }: { all: Payment[]; month: string; selected: string | null; onChanged: () => void }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [shown, setShown] = useState(PAGE);
  const filter = { month, type: params.get("type"), doc: params.get("doc"), q: params.get("q") };
  const list = filterPayments(all, filter);
  const open = all.find((p) => p.id === selected) ?? null;
  const qs = params.toString() ? `?${params}` : "";
  const drop = (key: string) => { const p = new URLSearchParams(params); p.delete(key); navigate(`/money/payments${selected ? `/${selected}` : ""}${p.toString() ? `?${p}` : ""}`); };
  const typeName = filter.type ? (list[0] ? typeOf(list[0]).label : filter.type) : null;
  return (
    <div className="hstack" style={{ alignItems: "flex-start", gap: 24, flexWrap: "nowrap" }}>
      <div className="stack grow" style={{ gap: 12 }}>
        {(filter.type || filter.doc || filter.q) && (
          <div className="hstack">
            <span className="small t2">Showing only</span>
            {filter.type && <button type="button" className="chip" onClick={() => drop("type")}>{typeName} ✕</button>}
            {filter.doc && <button type="button" className="chip" onClick={() => drop("doc")}>{filter.doc === "missing" ? "No invoice" : DOC_CHIP[filter.doc as keyof typeof DOC_CHIP]?.text ?? filter.doc} ✕</button>}
            {filter.q && <button type="button" className="chip" onClick={() => drop("q")}>“{filter.q}” ✕</button>}
          </div>
        )}
        <div className="card table">
          <div className="trow head">
            <span className="cell" style={{ width: 56 }}>Date</span><span className="cell grow">To / From</span><span className="cell" style={{ width: 130 }}>Paid by</span>
            <span className="cell" style={{ width: 96 }}>Document</span><span className="cell r" style={{ width: 130 }}>Amount</span>
          </div>
          {list.length === 0 && <p className="t2" style={{ padding: 12 }}>No payments match{month ? ` in ${monthOnly(month)}` : ""}.</p>}
          {list.slice(0, shown).map((p) => {
            const t = typeOf(p);
            const chip = DOC_CHIP[p.doc];
            return (
              <Link key={p.id} to={`/money/payments/${p.id}${qs}`} className={`trow${p.id === selected ? " selected" : ""}`}>
                <span className="cell small t2" style={{ width: 56 }}>{p.date ? shortDate(p.date) : "—"}</span>
                <span className="cell col grow"><span className="ellipsis" title={p.name}>{p.name}</span><span className="caption t3 hstack" style={{ gap: 6 }}><span className="dot" style={{ background: t.color }} />{t.label}</span></span>
                <span className="cell small t2" style={{ width: 130 }}>{p.paidBy}</span>
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
