// Overview: where the company stands today, how last month went, and cash over time.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AccountsResponse, type BalanceHistory, type LedgerSummary } from "../api/client";
import type { Approval, Forecast, Recommendation, Transaction } from "../api/types.gen";
import { useAsk } from "../components/AskOrdo";
import { CashChart } from "../components/CashChart";
import { Change, MonthSelect, PageHead, StatusLabel, Tile } from "../components/ui";
import { compareAmounts, isZero, lastFullMonth, monthFigures, monthOnly, percent, previousMonth, recentMonths, type MonthFigures } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { daysBetween, shortDate } from "../lib/dates";
import { useLive } from "../lib/live";
import { formatMoney } from "../lib/money";
import { requestRefresh, useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { plainName, whole } from "../lib/words";
import { monthAndBefore } from "../lib/monthSummary";
import { upcoming } from "./dashboard/model";
import { buildDecision } from "./inbox/model";
import { buildTodo, topThree, type TodoItem } from "./todo/model";

const longDay = (iso: string) => new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${iso}T12:00:00Z`));
const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

export function Overview() {
  const { companyId } = useCompany();
  const company = useCompanyInfo();
  const today = useToday();
  const refresh = useRefreshKey();
  const [month, setMonth] = useState<string | null>(null);
  const shown = month ?? lastFullMonth(today);
  const [flash, setFlash] = useState(false);
  useLive((e) => { if (e.type === "forecast.updated") { setFlash(true); setTimeout(() => setFlash(false), 4000); } });

  const now = useApi(() => Promise.all([
    none(api.accounts(companyId)), none(api.forecast(companyId)), none(api.balanceHistory(companyId)), none(api.inbox(companyId)),
  ]), [companyId, refresh]);
  const figures = useApi(() => Promise.all([
    monthAndBefore(companyId, shown),
    none(api.transactions(companyId)),
    none(api.counterparties(companyId)),
  ]), [companyId, shown, refresh]);

  const [accounts, forecast, history, inbox] = now.data ?? [null, null, null, null];
  const [[current, before], transactions, parties] = figures.data ?? [[null, null], null, null];
  const names = Object.fromEntries((parties?.items ?? []).map((c) => [c.id, plainName(c.name)]));
  const currency = company?.base_currency ?? forecast?.base_currency ?? "PLN";
  return (
    <>
      <PageHead title="Overview" sub={longDay(today)} />
      <section className="section">
        <h2>Today</h2>
        <div className="row">
          <CashCard accounts={accounts} forecast={forecast} loading={now.loading && !now.data} />
          <TodoCard items={inbox?.items ?? null} forecast={forecast} loading={now.loading && !now.data} />
        </div>
      </section>
      <MonthSection month={shown} months={recentMonths(today, 6)} onMonth={setMonth}
        summary={current?.summary ?? null} fromBank={current?.fromBank ?? false} before={before} transactions={transactions?.items ?? []} names={names} currency={currency} loading={figures.loading && !figures.data} />
      <CashSection history={history} forecast={forecast} flash={flash} />
    </>
  );
}

export function CashCard({ accounts, forecast, loading }: { accounts: AccountsResponse | null; forecast: Forecast | null; loading?: boolean }) {
  const coming = forecast ? upcoming(forecast).filter((u) => daysBetween(forecast.as_of_date, u.date) <= 14).slice(0, 4) : [];
  const total = accounts?.total_liquidity_base ?? forecast?.opening_balance ?? null;
  const cash = accounts?.items.filter((a) => a.include_in_liquidity) ?? [];
  return (
    <div className="card stack" style={{ gap: 16 }}>
      <div className="stack" style={{ gap: 4 }}>
        <span className="t2">Cash in the bank</span>
        <span className="hero">{loading ? "…" : total ? whole(total) : "—"}</span>
      </div>
      {cash.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          {cash.map((a) => <div key={a.id} className="kv"><span className="t2">{a.name}</span><span>{formatMoney(a.balance)}</span></div>)}
        </div>
      )}
      <hr className="divider" />
      <div className="stack" style={{ gap: 8 }}>
        <span className="small medium">Coming up</span>
        {forecast ? (
          coming.length ? (
            <div className="coming">
              {coming.map((u) => (
                <span key={u.id} style={{ display: "contents" }}>
                  <span className="t3">{shortDate(u.date)}</span>
                  <span className="t2">{u.label}</span>
                  <span className={`right${u.amount.amount.startsWith("-") ? "" : " good"}`}>{u.amount.amount.startsWith("-") ? "" : "+"}{whole(u.amount)}</span>
                </span>
              ))}
            </div>
          ) : <span className="small t3">Nothing expected in the next two weeks.</span>
        ) : <span className="small t3">{loading ? "…" : "No forecast yet."}</span>}
      </div>
    </div>
  );
}

function TodoCard({ items, forecast, loading }: { items: Recommendation[] | null; forecast: Forecast | null; loading?: boolean }) {
  const todo = items ? buildTodo(items, forecast) : null;
  return (
    <div className="card stack" style={{ gap: 8 }}>
      <div className="section-head">
        <h2>To-do</h2>
        {todo && <span className="small t3">{todo.count} open</span>}
        <span className="grow" />
        <Link to="/todo" className="small">See all</Link>
      </div>
      {loading && <span className="t3">…</span>}
      {todo && todo.count === 0 && <span className="t2">Nothing waits for you. Ordo will add a to-do when something needs your OK.</span>}
      {todo && topThree(todo).map((item) => <TodoRow key={item.id} item={item} />)}
    </div>
  );
}

/** One to-do: label, what it is, one line why, one button. Approving here runs the same simulated action as on To-do. */
export function TodoRow({ item }: { item: TodoItem }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function approve(rec: Recommendation) {
    setBusy(true);
    setError(null);
    try {
      setDone(await api.decide(rec.id, buildDecision(rec, "approve")));
      requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const p = item.primary;
  return (
    <div className="list-row todo-row">
      <div className="stack grow" style={{ gap: 4 }}>
        <StatusLabel level={done ? "approved" : item.level} />
        <span className="medium">{item.title}</span>
        <span className="small t2">{done ? done.execution.result : item.summary}</span>
        {error && <span className="small bad" role="alert">Not done: {error}</span>}
      </div>
      {done ? <span className="simulated">SIMULATED · {done.execution.reference}</span>
        : p.kind === "approve" && item.rec ? <button type="button" className="primary" disabled={busy} onClick={() => approve(item.rec!)}>{busy ? "Working…" : p.label}</button>
        : <button type="button" onClick={() => navigate(p.to ?? `/todo#${item.id}`)}>{p.kind === "details" ? "See details" : p.label}</button>}
    </div>
  );
}

function MonthSection({ month, months, onMonth, summary, fromBank, before, transactions, names, currency, loading }: {
  month: string; months: string[]; onMonth: (m: string) => void; summary: LedgerSummary | null; fromBank: boolean; before: LedgerSummary | null; transactions: Transaction[];
  names: Record<string, string>; currency: string; loading: boolean;
}) {
  const f = monthFigures(summary, currency);
  const prev = before && before.rows.length ? monthFigures(before, currency) : null;
  const vs = monthOnly(previousMonth(month));
  return (
    <section className="section">
      <div className="section-head">
        <MonthSelect value={month} months={months} onChange={onMonth} look="section" />
        {fromBank && <FromBank />}
        <span className="grow" />
        {prev && <span className="small t3">Compared with {vs}</span>}
      </div>
      {loading ? <p className="t3">…</p> : !summary ? <p className="t2">No month figures yet: the books for this company are empty.</p> : !f.hasData ? <p className="t2">No payments in {monthOnly(month)}.</p> : (
        <>
          <div className="row">
            <Tile label="Income" value={whole(f.income)} note={prev && <Change now={f.income} before={prev.income} upIsGood vs={vs} />} />
            <Tile label="Costs" value={whole(f.costs)} note={prev && <Change now={f.costs} before={prev.costs} upIsGood={false} vs={vs} />} />
            <Tile label="Left over" value={whole(f.leftOver)} note={prev && <Change now={f.leftOver} before={prev.leftOver} upIsGood vs={vs} />} />
          </div>
          <div className="row">
            <WhereItWent f={f} month={month} summary={summary} />
            <Explained f={f} month={month} summary={summary} transactions={transactions} names={names} />
          </div>
        </>
      )}
    </section>
  );
}

export function WhereItWent({ f, month, summary }: { f: MonthFigures; month: string; summary: LedgerSummary }) {
  const entries = (key: string) => summary.rows.find((r) => r.key === key)?.entries ?? 0;
  return (
    <div className="card stack" style={{ gap: 16, flex: 2 }}>
      <div className="stack" style={{ gap: 2 }}>
        <h2>Where the money went</h2>
        <span className="small t2">{whole(f.costs)} spent in {monthOnly(month)}</span>
      </div>
      <div className="hstack" style={{ gap: 32 }}>
        <div className="stack" style={{ gap: 0 }}><span className="small t2">Fixed every month</span><span className="medium">{whole(f.fixed)}</span></div>
        <div className="stack" style={{ gap: 0 }}><span className="small t2">Everything else</span><span className="medium">{whole(f.other)}</span></div>
      </div>
      <div className="cost-bar" role="img" aria-label="Costs by type">
        {f.types.map((t) => <span key={t.type.key} title={`${t.type.label}: ${whole(t.amount)}`} style={{ background: t.type.color, width: `${Math.max(0.5, percent(t.amount.amount, f.costs.amount))}%` }} />)}
      </div>
      <div className="stack" style={{ gap: 0 }}>
        {f.types.map((t) => (
          <Link key={t.type.key} to={`/money/payments?month=${month}&type=${t.type.key}`} className="list-row cost-row">
            <span className="dot" style={{ background: t.type.color }} />
            <span>{t.type.label}</span>
            <span className="small t3 grow">{t.type.key === "unexplained" ? `${entries("other")} payments` : t.type.tag}</span>
            <span>{whole(t.amount)}</span>
            <span className="chev" aria-hidden="true">›</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Explained({ f, month, summary, transactions, names }: { f: MonthFigures; month: string; summary: LedgerSummary; transactions: Transaction[]; names: Record<string, string> }) {
  const explained = 100 - percent(f.unexplained.amount, f.costs.amount);
  // The biggest payments of the month that still have no type or no invoice.
  const open = transactions
    .filter((t) => t.booking_date.startsWith(month) && t.amount_base.amount.startsWith("-") && (t.category === "other" || t.match_status === "missing_document"))
    .sort((a, b) => compareAmounts(a.amount_base.amount, b.amount_base.amount)).slice(0, 3);
  return (
    <div className="card stack" style={{ gap: 12 }}>
      <h2>Explained</h2>
      <span className="hero">{isZero(f.costs.amount) ? "—" : `${explained}%`}</span>
      <span className="t2">of {monthOnly(month)}'s costs are sorted into a type.</span>
      <div className="progress"><span style={{ width: `${explained}%` }} /></div>
      <div className="kv"><span className="t2">Payments without an invoice</span><span>{summary.kpis.documents_missing}</span></div>
      <div className="kv"><span className="t2">Not explained yet</span><span>{whole(f.unexplained)}</span></div>
      {open.length > 0 && (
        <div className="stack" style={{ gap: 8, marginTop: 4 }}>
          <span className="small t2">Biggest ones</span>
          {open.map((t) => (
            <Link key={t.id} to={`/money/payments/${t.id}?month=${month}`} className="kv" style={{ color: "inherit" }}>
              <span className="stack" style={{ gap: 0 }}>
                <span>{names[t.counterparty_id ?? ""] ?? t.counterparty_name_raw ?? t.description}</span>
                <span className="caption t3">{t.match_status === "missing_document" ? "no invoice" : "no type yet"}</span>
              </span>
              <span>{whole({ amount: t.amount_base.amount.replace("-", ""), currency: t.amount_base.currency })}</span>
            </Link>
          ))}
        </div>
      )}
      <span className="grow" />
      <Link to={`/money/payments?month=${month}&doc=missing`} className="button" style={{ alignSelf: "flex-start" }}>Check them</Link>
    </div>
  );
}

function CashSection({ history, forecast, flash }: { history: BalanceHistory | null; forecast: Forecast | null; flash: boolean }) {
  const ask = useAsk();
  const alert = forecast?.alerts.find((a) => a.type === "cash_gap");
  const weeks = forecast ? Math.round(forecast.horizon_days / 7) : 6;
  return (
    <section className="section" id="cash">
      <div className="section-head">
        <div className="stack grow" style={{ gap: 2 }}>
          <h2>Cash over time</h2>
          <span className="small t2">{history ? `The last 3 months, and the next ${weeks} weeks from payments we already know about` : `The next ${weeks} weeks, from payments we already know about`}</span>
        </div>
        {history && <span className="legend"><i />In the bank</span>}
        {forecast && <span className="legend"><i className="dashed" />Expected</span>}
        <button type="button" onClick={() => ask.open("What if I hire a developer for 15,000 PLN a month from January?")}>Add a plan</button>
      </div>
      <div className="card stack">
        <CashChart history={history} forecast={forecast} flash={flash} />
        {forecast && (
          <p className="small t2">
            Lowest point: {whole(forecast.min_balance.amount)} on {shortDate(forecast.min_balance.date)}.
            {alert?.date_to ? ` Back above zero on ${shortDate(alert.date_to)}.` : ""}
          </p>
        )}
      </div>
    </section>
  );
}

/** Said wherever a month is summed from the bank lines because its payments are not in the books yet. */
export function FromBank() {
  return <span className="chip warn" title="Summed from the bank lines. These payments are not matched to invoices and booked yet.">From the bank, not checked yet</span>;
}
