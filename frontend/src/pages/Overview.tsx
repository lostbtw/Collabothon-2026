// Overview: where the company stands today, how last month went, and cash over time.
import { useEffect, useRef, useState, type RefObject } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AccountsResponse, type BalanceHistory, type LedgerSummary } from "../api/client";
import type { Approval, Forecast, Money, Recommendation, Transaction } from "../api/types.gen";
import { useAsk } from "../components/AskOrdo";
import { CashChart } from "../components/CashChart";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { Change, Chevron, DoneChip, MonthSelect, PageHead, SimButton, Skeleton, StatusLabel, Tile } from "../components/ui";
import { compareAmounts, isZero, monthFigures, monthOnly, percent, previousMonth, recentMonths, type MonthFigures } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { shortDate } from "../lib/dates";
import { useLive } from "../lib/live";
import { formatMoney } from "../lib/money";
import { requestRefresh, useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { initials, plainName, whole } from "../lib/words";
import { monthAndBefore } from "../lib/monthSummary";
import { upcoming, type Upcoming } from "./dashboard/model";
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
  const cashRef = useRef<HTMLDivElement>(null);
  const todoRef = useRef<HTMLDivElement>(null);
  const todoHeight = useRestingHeight(todoRef, cashRef);
  return (
    <>
      <PageHead title="Overview" sub="Your cash today, what waits for you, how the month went and what is coming." />
      <section className="section">
        <h2>Today</h2>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div ref={cashRef}><CashCard accounts={accounts} forecast={forecast} loading={now.loading && !now.data} fillTo={todoHeight} /></div>
          <div ref={todoRef}><TodoCard items={inbox?.items ?? null} forecast={forecast} loading={now.loading && !now.data} /></div>
        </div>
      </section>
      <MonthSection month={shown} months={recentMonths(today, 6)} onMonth={setMonth}
        summary={current?.summary ?? null} before={before} transactions={transactions?.items ?? []} names={names} currency={currency} loading={figures.loading && !figures.data} />
      <CashSection history={history} forecast={forecast} flash={flash} />
      <TaxSection forecast={forecast} dueIn30={current?.summary.kpis.tax_due_next_30d ?? null} loading={now.loading && !now.data} />
    </>
  );
}

// The To-do card's height without the summaries it reveals on hover, while it sits beside the given card; null when stacked.
function useRestingHeight(ref: RefObject<HTMLElement | null>, beside: RefObject<HTMLElement | null>): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const revealed = [...el.querySelectorAll<HTMLElement>(".on-hover")].reduce((sum, e) => sum + e.offsetHeight, 0);
      setHeight(beside.current && beside.current.offsetTop === el.offsetTop ? el.offsetHeight - revealed : null);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, beside]);
  return height;
}

const COMING_SHOWN = 5;

export function CashCard({ accounts, forecast, loading, fillTo }: { accounts: AccountsResponse | null; forecast: Forecast | null; loading?: boolean; fillTo?: number | null }) {
  const [all, setAll] = useState(false);
  const everything = forecast ? upcoming(forecast) : [];
  const coming = everything.slice(0, COMING_SHOWN);
  const total = accounts?.total_liquidity_base ?? forecast?.opening_balance ?? null;
  const cash = accounts?.items.filter((a) => a.include_in_liquidity) ?? [];
  return (
    <div className="card stack" style={{ gap: 16, minHeight: fillTo ?? undefined }}>
      <div className="stack" style={{ gap: 4 }}>
        <span className="t2">Bank balance{cash.length > 1 ? ` · ${cash.length} accounts` : ""}</span>
        {loading ? <span className="skeleton big" /> : (
          <div className="balance-hover" tabIndex={cash.length ? 0 : undefined} aria-describedby={cash.length ? "balance-accounts" : undefined}>
            <span className="hero balance-total">{total ? formatMoney(total) : "—"}</span>
            {cash.length > 0 && (
              <div className="balance-pop" id="balance-accounts" role="tooltip">
                <span className="explained-label">By account</span>
                {cash.map((a) => <div key={a.id} className="kv"><span className="t2">{a.name}</span><span className="medium">{formatMoney(a.balance)}</span></div>)}
              </div>
            )}
          </div>
        )}
      </div>
      <hr className="divider" />
      <div className="stack" style={{ gap: 8, flex: 1, minHeight: 0 }}>
        <div className="section-head">
          <span className="small medium grow">Coming up</span>
          {everything.length > coming.length && <button type="button" className="link-button small" onClick={() => setAll(true)}>See all</button>}
        </div>
        {forecast ? (
          coming.length ? <ComingList items={coming} /> : <span className="small t3">Nothing expected yet.</span>
        ) : (loading ? <span className="skeleton line" style={{ width: "70%" }} /> : <span className="small t3">No forecast yet.</span>)}
      </div>
      {all && forecast && (
        <Modal title="Coming up" onClose={() => setAll(false)}
          head={<span className="small t2">Everything Ordo expects in the next {Math.round(forecast.horizon_days / 7)} weeks, from known payments</span>}>
          <ComingList items={everything} />
        </Modal>
      )}
    </div>
  );
}

function ComingList({ items }: { items: Upcoming[] }) {
  return (
    <div className="coming">
      {items.map((u) => (
        <span key={u.id} style={{ display: "contents" }}>
          <span className="t3">{shortDate(u.date)}</span>
          <span className="t2">{u.label}</span>
          <span className={`right${u.amount.amount.startsWith("-") ? "" : " good"}`}>{u.amount.amount.startsWith("-") ? "" : "+"}{whole(u.amount)}</span>
        </span>
      ))}
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
            <span className="medium">{estimate ? c.label.slice(0, -ESTIMATE.length) : c.label}</span>
            {estimate && <span className="chip warn">estimate</span>}
          </span>
          {open && c.explainer && <span className="small t2" style={{ marginTop: 2 }}>{c.explainer}</span>}
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
          <div className="row" style={{ alignItems: "flex-start" }}>
            <WhereItWent f={f} month={month} summary={summary} />
            <ReviewCard f={f} month={month} summary={summary} transactions={transactions} names={names} />
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
      <h2>Where the money went</h2>
      <div className="spend-summary">
        <SpendPart label="Fixed every month" amount={f.fixed} share={percent(f.fixed.amount, f.costs.amount)} />
        <SpendPart label="Everything else" amount={f.other} share={percent(f.other.amount, f.costs.amount)} />
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

function SpendPart({ label, amount, share }: { label: string; amount: Money; share: number }) {
  return (
    <div className="spend-part">
      <span className="small t2">{label}</span>
      <span className="spend-value">{whole(amount)}</span>
      <span className="caption t3">{share}% of costs</span>
    </div>
  );
}

function ReviewCard({ f, month, summary, transactions, names }: { f: MonthFigures; month: string; summary: LedgerSummary; transactions: Transaction[]; names: Record<string, string> }) {
  const unsorted = percent(f.unexplained.amount, f.costs.amount);
  const untyped = summary.rows.find((r) => r.key === "other")?.entries ?? 0;
  const missing = summary.kpis.documents_missing;
  const open = transactions
    .filter((t) => t.booking_date.startsWith(month) && t.amount_base.amount.startsWith("-") && (t.category === "other" || t.match_status === "missing_document"))
    .sort((a, b) => compareAmounts(a.amount_base.amount, b.amount_base.amount)).slice(0, 3);
  return (
    <div className="card stack review" style={{ gap: 16 }}>
      <div className="stack" style={{ gap: 2 }}>
        <h2>Review</h2>
        <span className="small t2">{monthOnly(month)}'s costs: sorted and backed by an invoice</span>
      </div>

      <div className="review-stats">
        <ReviewStat done={untyped === 0} value={isZero(f.costs.amount) ? "—" : untyped > 0 && unsorted === 0 ? "<1%" : `${unsorted}%`} label="of costs not sorted"
          to={`/money/payments?month=${month}&type=unexplained`} />
        <ReviewStat done={missing === 0} value={String(missing)} label={missing === 1 ? "payment without an invoice" : "payments without an invoice"}
          to={`/money/payments?month=${month}&doc=missing`} />
      </div>

      {open.length > 0 && (
        <div className="stack" style={{ gap: 0 }}>
          <span className="explained-label">Biggest open payments</span>
          {open.map((t) => {
            const name = names[t.counterparty_id ?? ""] ?? t.counterparty_name_raw ?? t.description;
            return (
              <ExplainedRow key={t.id} mark={<span className="check-mark neutral" aria-hidden="true">{initials(name)}</span>} title={name}
                to={`/money/payments/${t.id}?month=${month}`}
                detail={<>{shortDate(t.booking_date)} · <span className="warn">{t.match_status === "missing_document" ? "no invoice" : "no type"}</span></>}
                value={whole({ amount: t.amount_base.amount.replace("-", ""), currency: t.amount_base.currency })} />
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReviewStat({ done, value, label, to }: { done: boolean; value: string; label: string; to: string }) {
  return (
    <Link to={to} className={`review-stat ${done ? "done" : "open"}`}>
      <span className="hstack" style={{ gap: 8, flexWrap: "nowrap" }}>
        <span className="review-value grow">{value}</span>
        {done ? <span className="check-mark ok small-mark" role="img" aria-label="Done"><Icon name="check" size={14} /></span> : <Chevron />}
      </span>
      <span className="medium">{label}</span>
    </Link>
  );
}

function ExplainedRow({ mark, title, detail, value, to }: { mark: React.ReactNode; title: string; detail: React.ReactNode; value: string | null; to: string }) {
  return (
    <Link to={to} className="list-row explained-row">
      {mark}
      <span className="stack grow" style={{ gap: 0 }}>
        <span className="ellipsis">{title}</span>
        <span className="caption t3">{detail}</span>
      </span>
      {value && <span className="medium explained-amount">{value}</span>}
      <Chevron />
    </Link>
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
