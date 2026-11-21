// Overview: where the company stands today, how last month went, and cash over time.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AccountsResponse, type BalanceHistory, type LedgerSummary } from "../api/client";
import type { Approval, Forecast, Money, Recommendation, Transaction } from "../api/types.gen";
import { useAsk } from "../components/AskOrdo";
import { CashChart } from "../components/CashChart";
import { Change, DoneChip, MonthSelect, PageHead, SimButton, Skeleton, StatusLabel, Tile } from "../components/ui";
import { compareAmounts, isZero, monthFigures, monthOnly, percent, previousMonth, recentMonths, type MonthFigures } from "../lib/costTypes";
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

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

export function Overview() {
  const { companyId } = useCompany();
  const company = useCompanyInfo();
  const today = useToday();
  const refresh = useRefreshKey();
  const [month, setMonth] = useState<string | null>(null);
  const shown = month ?? today.slice(0, 7);
  const [flash, setFlash] = useState(false);
  useLive((e) => { if (e.type === "forecast.updated") { setFlash(true); setTimeout(() => setFlash(false), 4000); } });

  const now = useApi(() => Promise.all([
    none(api.accounts(companyId)), none(api.forecast(companyId)), none(api.balanceHistory(companyId)), none(api.inbox(companyId)),
  ]), [companyId, refresh]);
  const figures = useApi(() => monthAndBefore(companyId, shown), [companyId, shown, refresh]);
  const lines = useApi(() => Promise.all([none(api.transactions(companyId)), none(api.counterparties(companyId))]), [companyId, refresh]);

  const [accounts, forecast, history, inbox] = now.data ?? [null, null, null, null];
  const [current, before] = figures.data ?? [null, null];
  const [transactions, parties] = lines.data ?? [null, null];
  const names = Object.fromEntries((parties?.items ?? []).map((c) => [c.id, plainName(c.name)]));
  const currency = company?.base_currency ?? forecast?.base_currency ?? "PLN";
  return (
    <>
      <PageHead title="Overview" sub="Your cash today, what waits for you, how the month went and what is coming." />
      <section className="section">
        <h2>Today</h2>
        <div className="row">
          <CashCard accounts={accounts} forecast={forecast} loading={now.loading && !now.data} />
          <TodoCard items={inbox?.items ?? null} forecast={forecast} loading={now.loading && !now.data} />
        </div>
      </section>
      <MonthSection month={shown} months={recentMonths(today, 6)} onMonth={setMonth}
        summary={current?.summary ?? null} before={before} transactions={transactions?.items ?? []} names={names} currency={currency} loading={figures.loading && !figures.data} />
      <CashSection history={history} forecast={forecast} flash={flash} />
      <TaxSection forecast={forecast} dueIn30={current?.summary.kpis.tax_due_next_30d ?? null} loading={now.loading && !now.data} />
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
        <span className="t2">Bank balance</span>
        {loading ? <span className="skeleton big" /> : <span className="hero">{total ? whole(total) : "—"}</span>}
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
        ) : (loading ? <span className="skeleton line" style={{ width: "70%" }} /> : <span className="small t3">No forecast yet.</span>)}
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
      {loading && <><span className="skeleton line" style={{ width: "80%" }} /><span className="skeleton line" style={{ width: "60%" }} /><span className="skeleton line" style={{ width: "70%" }} /></>}
      {todo && todo.count === 0 && <span className="t2">Nothing waits for you. Ordo will add a to-do when something needs your confirmation.</span>}
      {todo && topThree(todo).map((item) => <TodoRow key={item.id} item={item} />)}
    </div>
  );
}

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
        {done ? <span className="small t2">{done.execution.result}</span> : <span className="small t2 on-hover">{item.summary}</span>}
        {error && <span className="small bad" role="alert">Not done: {error}</span>}
      </div>
      {done ? <DoneChip reference={done.execution.reference} result={done.execution.result} />
        : p.kind === "approve" && item.rec ? <SimButton label={p.label} busy={busy} what={item.rec.proposed_action?.preview} onClick={() => approve(item.rec!)} />
        : <button type="button" onClick={() => navigate(p.to ?? `/todo#${item.id}`)}>{p.kind === "details" ? "See details" : p.label}</button>}
    </div>
  );
}

const ESTIMATE = " (estimate)";
const OP_SIGN: Record<string, string> = { start: "", plus: "+", minus: "−", equals: "=", note: "" };

const monthInWords = (label: string) => label.replace(" (JPK_V7M)", "").replace(/\b(\d{2})\/(\d{4})\b/,
  (_, m: string, y: string) => `${new Date(Number(y), Number(m) - 1, 1).toLocaleString("en-GB", { month: "long" })} ${y}`);

type TaxComponent = Forecast["components"][number] & { date: string };

function TaxRow({ c, first, open, onToggle }: { c: TaxComponent; first: boolean; open: boolean; onToggle: () => void }) {
  const estimate = c.label.endsWith(ESTIMATE);
  return (
    <div style={first ? undefined : { borderTop: "1px solid var(--border)" }}>
      <div role="button" tabIndex={0} aria-expanded={open} onClick={onToggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
        style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 0", cursor: "pointer" }}>
        <span className="t3" style={{ minWidth: 56 }}>{shortDate(c.date)}</span>
        <div className="stack grow" style={{ gap: 2 }}>
          <span className="hstack" style={{ gap: 8 }}>
            <span className="medium">{monthInWords(estimate ? c.label.slice(0, -ESTIMATE.length) : c.label)}</span>
            {estimate && <span className="chip warn">estimate</span>}
          </span>
          {c.explainer && <span className="small t2" style={{ marginTop: 2 }}>{c.explainer}</span>}
        </div>
        <span className="medium">{whole({ amount: c.amount_base.amount.replace("-", ""), currency: c.amount_base.currency })}</span>
        <span className="button" aria-hidden style={{ height: 30, padding: "0 12px", fontSize: 13, minWidth: 104, gap: 6 }}>
          {open ? "Hide details" : "Details"}
          <span style={{ display: "inline-block", transform: open ? "rotate(-90deg)" : "rotate(90deg)", transition: "transform .15s" }}>›</span>
        </span>
      </div>
      {open && <TaxDetails c={c} />}
    </div>
  );
}

const PANEL_TITLE: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text-3)" };
const NUM: React.CSSProperties = { fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const SOURCE = /^(.*), (\d{4}-\d{2}-\d{2}), (.*)$/;

function PanelPart({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <span style={PANEL_TITLE}>{title}</span>
      {children}
    </div>
  );
}

function TaxDetails({ c }: { c: TaxComponent }) {
  const all = c.breakdown ?? [];
  const end = all.length - [...all].reverse().findIndex((s) => s.op !== "note");
  const steps = all.slice(0, end > all.length ? 0 : end);
  const notes = all.slice(steps.length);
  const last = steps.length - 1;
  const rule = c.evidence?.find((e) => e.kind === "rule");
  const sources = (c.evidence ?? []).filter((e) => e.kind !== "rule");
  const formula = c.schedule?.split(": ").slice(1).join(": ") ?? "";
  const due = c.schedule?.split(": ")[0];
  return (
    <div className="stack" style={{ gap: 20, margin: "4px 0 20px 72px" }}>
      {(steps.length > 0 || formula) && (
        <PanelPart title="How we got this number">
          {steps.length === 0 ? <span className="small">{formula}</span> : (
            <div className="stack" style={{ gap: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
              {steps.map((s, i) => {
                const total = i === last;
                const subtotal = s.op === "equals" && !total;
                if (s.op === "note") return (
                  <div key={i} style={{ padding: "8px 14px", borderTop: i ? "1px solid var(--border)" : undefined, background: "var(--sunken)", fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{s.label}</div>
                );
                return (
                  <div key={i} className="hstack" style={{ gap: 12, padding: "10px 14px", borderTop: i ? "1px solid var(--border)" : undefined, background: total ? "var(--accent-soft)" : undefined }}>
                    <span style={{ width: 20, height: 20, flex: "none", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--pill)", background: OP_SIGN[s.op] ? "var(--sunken)" : "transparent", color: "var(--text-2)", fontSize: 13 }}>{OP_SIGN[s.op]}</span>
                    <span className="grow" style={{ fontSize: 14, fontWeight: total || subtotal ? 600 : 400, color: total || subtotal ? "var(--text)" : "var(--text-2)" }}>{s.label}</span>
                    {s.amount && <span style={{ ...NUM, fontSize: total ? 16 : 14, fontWeight: total || subtotal ? 600 : 500, color: total ? "var(--accent)" : "var(--text)" }}>{formatMoney(s.amount)}</span>}
                  </div>
                );
              })}
            </div>
          )}
          {notes.map((n, i) => <span key={i} className="small t3">ⓘ {n.label}</span>)}
        </PanelPart>
      )}
      {due && (
        <PanelPart title="Why this date">
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", rowGap: 6, columnGap: 16 }}>
            <span className="small t3">Payment date</span>
            <span className="small medium">{shortDate(c.date)}</span>
            <span className="small t3">Deadline</span>
            <span className="small">{due.charAt(0).toUpperCase() + due.slice(1)}</span>
            {rule && <><span className="small t3">Rule</span><span className="small t2">{rule.label}</span></>}
          </div>
        </PanelPart>
      )}
      {sources.length > 0 && (
        <PanelPart title={`Based on ${sources.length} ${sources.length === 1 ? "item" : "items"}`}>
          <div className="stack" style={{ gap: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
            {sources.map((e, i) => {
              const m = SOURCE.exec(e.label);
              const row = (
                <span className="hstack" style={{ gap: 12, padding: "9px 14px", borderTop: i ? "1px solid var(--border)" : undefined }}>
                  <span className="chip neutral" style={{ height: 20, fontSize: 11 }}>{e.kind === "document" ? "Invoice" : "Payment"}</span>
                  <span className="small medium grow">{m ? m[1] : e.label}</span>
                  {m && <span className="small t3">{shortDate(m[2])}</span>}
                  {m && <span className="small" style={{ ...NUM, minWidth: 110, textAlign: "right" }}>{m[3]}</span>}
                  {e.url && <span className="t3" aria-hidden>›</span>}
                </span>
              );
              return e.url ? <Link key={e.id} to={e.url} style={{ color: "inherit", textDecoration: "none" }}>{row}</Link> : <div key={e.id}>{row}</div>;
            })}
          </div>
        </PanelPart>
      )}
    </div>
  );
}

/** Every tax and social-security payment the forecast expects; each row opens the engine's calculation behind it. */
export function TaxSection({ forecast, dueIn30, loading }: { forecast: Forecast | null; dueIn30: Money | null; loading?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const taxes = (forecast?.components ?? [])
    .flatMap((c) => (c.kind === "tax" || c.kind === "social_security") && c.dates?.[0] ? [{ ...c, date: c.dates[0] }] : [])
    .sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
  return (
    <section className="section" id="taxes">
      <div className="section-head">
        <div className="stack grow" style={{ gap: 2 }}>
          <h2>Taxes</h2>
          <span className="small t2">Tax payments coming up. Click a payment to see how we calculated it and what it is based on.</span>
        </div>
        {dueIn30 && <span className="small t2">Due in the next 30 days: <span className="medium">{whole(dueIn30)}</span></span>}
      </div>
      <div className="card stack" style={{ gap: 0, paddingTop: 4, paddingBottom: 4 }}>
        {loading ? <Skeleton rows={4} /> : !forecast ? <span className="t2">No forecast yet.</span>
          : taxes.length === 0 ? <span className="t2">No tax payment in the next {forecast.horizon_days} days.</span>
          : taxes.map((c, i) => <TaxRow key={c.id} c={c} first={i === 0} open={open === c.id} onToggle={() => setOpen(open === c.id ? null : c.id)} />)}
      </div>
    </section>
  );
}

function MonthSection({ month, months, onMonth, summary, before, transactions, names, currency, loading }: {
  month: string; months: string[]; onMonth: (m: string) => void; summary: LedgerSummary | null; before: LedgerSummary | null; transactions: Transaction[];
  names: Record<string, string>; currency: string; loading: boolean;
}) {
  const f = monthFigures(summary, currency);
  const prev = before && before.rows.length ? monthFigures(before, currency) : null;
  const vs = monthOnly(previousMonth(month));
  return (
    <section className="section">
      <div className="section-head">
        <MonthSelect value={month} months={months} onChange={onMonth} look="section" />
        <span className="grow" />
        {prev && <span className="small t3">Compared with {vs}</span>}
      </div>
      {loading ? <Skeleton tiles={3} rows={4} /> : !summary ? <p className="t2">No month figures yet: the books for this company are empty.</p> : !f.hasData ? <p className="t2">No payments in {monthOnly(month)}.</p> : (
        <>
          <div className="row">
            <Tile label="Income" value={whole(f.income)} note={prev && <Change now={f.income} before={prev.income} upIsGood />} />
            <Tile label="Costs" value={whole(f.costs)} note={prev && <Change now={f.costs} before={prev.costs} upIsGood={false} />} />
            <Tile label="Left over" value={whole(f.leftOver)} note={prev && <Change now={f.leftOver} before={prev.leftOver} upIsGood />} />
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
      <Link to={`/money/payments?month=${month}&doc=missing`} className="button" style={{ alignSelf: "flex-start" }}>Review</Link>
    </div>
  );
}

function CashSection({ history, forecast, flash }: { history: BalanceHistory | null; forecast: Forecast | null; flash: boolean }) {
  const ask = useAsk();
  const recovers = forecast && forecast.min_balance.amount.amount.startsWith("-")
    ? forecast.points.find((p) => p.date > forecast.min_balance.date && !p.balance.startsWith("-"))?.date ?? null : null;
  const weeks = forecast ? Math.round(forecast.horizon_days / 7) : 6;
  return (
    <section className="section" id="cash">
      <div className="section-head">
        <div className="stack grow" style={{ gap: 2 }}>
          <h2>Balance over time</h2>
          <span className="small t2">{history ? `Last 3 months, and a ${weeks}-week forecast from known payments` : `A ${weeks}-week forecast from known payments`}</span>
        </div>
        {history && <span className="legend"><i />In the bank</span>}
        {forecast && <span className="legend"><i className="dashed" />Expected</span>}
        {forecast?.points.some((p) => p.low && p.high) && <span className="legend"><b className="legend-band" />Likely range</span>}
        <button type="button" onClick={() => ask.open("What if I hire a developer for 15,000 PLN a month from January?")}>Add a plan</button>
      </div>
      <div className="card stack">
        <CashChart history={history} forecast={forecast} flash={flash} />
        {forecast && (
          <p className="small t2">
            Lowest point: {whole(forecast.min_balance.amount)} on {shortDate(forecast.min_balance.date)}.
            {recovers ? ` Back above zero on ${shortDate(recovers)}.` : ""}
          </p>
        )}
      </div>
    </section>
  );
}
