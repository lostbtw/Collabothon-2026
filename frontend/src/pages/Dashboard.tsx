import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type AccountsResponse, type FxExposure, type InboxResponse, type LedgerSummary } from "../api/client";
import type { Forecast, Money, Transaction } from "../api/types.gen";
import { ForecastChart, type ChartView } from "../components/ForecastChart";
import { Icon } from "../components/Icon";
import { Evidence, More, MoreGroup } from "../components/More";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { useLive } from "../lib/live";
import { formatMoney, isNegative } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { dailyBalances, dataNotes, upcoming, weather } from "./dashboard/model";

const VIEW_KEY = "ordo.home.chart";
const words = (s: string) => s.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());

/** The owner's chart settings, remembered in this browser. */
function savedView(): Partial<ChartView> {
  try {
    return JSON.parse(window.localStorage.getItem(VIEW_KEY) ?? "{}") as Partial<ChartView>;
  } catch {
    return {};
  }
}

export function Dashboard() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  // Cash must load. A company may have no forecast yet; the rest only adds a widget when it is there.
  const state = useApi(
    () => Promise.all([
      api.accounts(companyId),
      api.forecast(companyId).catch(() => null),
      api.ledgerSummary(companyId).catch(() => null),
      api.inbox(companyId).catch(() => null),
      api.transactions(companyId).then((t) => t.items).catch(() => []),
      api.fxExposure(companyId).then((x) => x.items).catch(() => []),
    ]),
    [companyId, refresh],
  );
  // A live forecast update: pulse the low point and say what it was before (the shell re-reads the data).
  const [previousLow, setPreviousLow] = useState<Money | null>(null);
  useLive((e) => {
    if (e.type !== "forecast.updated") return;
    const was = e.payload.min_balance_previous as Money | undefined;
    setPreviousLow(was && typeof was.amount === "string" ? was : null);
    setTimeout(() => setPreviousLow(null), 8000);
  });
  return (
    <PageState state={state} keepWhileLoading>
      {([accounts, forecast, summary, inbox, transactions, fx]) => (
        <DashboardView accounts={accounts} forecast={forecast} summary={summary} inbox={inbox} transactions={transactions} fx={fx} previousLow={previousLow} initialView={savedView()} />
      )}
    </PageState>
  );
}

type ViewProps = {
  accounts: AccountsResponse; forecast: Forecast | null; summary: LedgerSummary | null; inbox: InboxResponse | null;
  transactions?: Transaction[]; fx?: FxExposure[]; previousLow?: Money | null; initialView?: Partial<ChartView>;
};

export function DashboardView({ accounts, forecast, summary, inbox, transactions = [], fx = [], previousLow, initialView }: ViewProps) {
  const [view, setView] = useState<ChartView>({ days: initialView?.days ?? forecast?.horizon_days ?? 45, events: initialView?.events ?? true, buffer: initialView?.buffer ?? false });
  function change(next: Partial<ChartView>) {
    const merged = { ...view, ...next };
    setView(merged);
    try {
      window.localStorage.setItem(VIEW_KEY, JSON.stringify(merged));
    } catch {
      // Not remembered; the chart still changes.
    }
  }

  const cash = accounts.items.filter((a) => a.include_in_liquidity && a.balance);
  const waiting = inbox?.items.filter((r) => r.control_level === "approval_required") ?? [];
  const fix = waiting.find((r) => r.agent === "liquidity");
  const notes = dataNotes(transactions);
  const w = forecast ? weather(forecast) : null;
  const low = forecast?.min_balance;
  const coming = forecast ? upcoming(forecast) : [];
  const costs = (summary?.rows ?? []).filter((r) => isNegative(r.amount_base)).sort((a, b) => Number(a.amount_base.amount) - Number(b.amount_base.amount));
  const biggest = costs.length ? Math.abs(Number(costs[0].amount_base.amount)) : 1;
  const ranges = forecast ? [...new Set([14, 30, forecast.horizon_days])].filter((d) => d <= forecast.horizon_days) : [];

  return (
    <>
      <div className="hstack"><h1>Home</h1>{forecast && <span className="muted">as of {shortDate(forecast.as_of_date)}</span>}</div>

      <div className="tiles">
        <Tile label={forecast ? "Cash today" : "Cash"} value={accounts.total_liquidity_base ? formatMoney(accounts.total_liquidity_base, { decimals: !forecast }) : cash.map((a) => formatMoney(a.balance)).join(" + ")}
          sub={cash.length > 1 ? cash.map((a) => formatMoney(a.balance)).join(" + ") : `${cash.length} account${cash.length === 1 ? "" : "s"}`} />
        {forecast && w && low ? (
          <div className={`card tile weather ${w.kind}`}>
            <div className="hstack tertiary"><Icon name={({ storm: "storm", cloudy: "cloud", sunny: "sun" } as const)[w.kind]} size={18} />Cash weather</div>
            <div className="tile-value">{w.headline}</div>
            <div className={`small ${isNegative(low.amount) ? "danger" : "muted"}`}>Lowest {formatMoney(low.amount, { decimals: false })} on {shortDate(low.date)}{previousLow ? ` (was ${formatMoney(previousLow, { decimals: false })})` : ""}</div>
            {fix && <Link to={`/inbox/${fix.id}`} className="button primary" style={{ alignSelf: "flex-start", marginTop: 4 }}>See the fix</Link>}
          </div>
        ) : (
          <Tile label="Forecast" value="—" sub="No forecast for this company yet." />
        )}
        {summary && <Tile label="Owed to the team" value={formatMoney(summary.kpis.reimbursements_owed, { decimals: false })} sub="not visible on the bank account" />}
        {summary?.kpis.tax_due_next_30d && <Tile label="Tax due in 30 days" value={formatMoney(summary.kpis.tax_due_next_30d, { decimals: false })} sub={`VAT lost this year: ${formatMoney(summary.kpis.vat_lost_ytd)}`} />}
        {inbox && <Tile label="Waiting for you" value={String(waiting.length)} sub={waiting.length === 1 ? "decision" : "decisions"} to="/inbox" />}
      </div>

      {forecast && (
        <div className="card stack">
          <div className="hstack">
            <span className="tertiary grow">Cash forecast</span>
            <div className="hstack" role="group" aria-label="Range">
              {ranges.map((d) => <button key={d} type="button" className={view.days === d ? "selected" : "outline"} aria-pressed={view.days === d} onClick={() => change({ days: d })}>{d} days</button>)}
            </div>
            <label className="toggle"><input type="checkbox" checked={view.events} onChange={(e) => change({ events: e.target.checked })} />Payments</label>
            {forecast.safety_buffer && <label className="toggle"><input type="checkbox" checked={view.buffer} onChange={(e) => change({ buffer: e.target.checked })} />Safety buffer</label>}
          </div>
          <ForecastChart forecast={forecast} flash={Boolean(previousLow)} view={view} />
        </div>
      )}

      <div className="grid2">
        {forecast && (
          <Widget title="Coming up" count={coming.length}>
            {coming.map((u) => {
              const row = (
                <>
                  <span className="tertiary when">{shortDate(u.date)}</span>
                  <span className="grow">{u.label}</span>
                  <span className="caption muted">{Math.round(u.confidence * 100)}% sure</span>
                  <span className={`medium amount${isNegative(u.amount) ? "" : " positive"}`}>{formatMoney(u.amount, { decimals: false })}</span>
                </>
              );
              const title = u.source ? `Source: ${u.source}.${u.url ? " Click to open the rows." : ""}` : undefined;
              return u.url ? <Link key={u.id} to={u.url} className="wrow rowlink" title={title}>{row}</Link> : <div key={u.id} className="wrow" title={title}>{row}</div>;
            })}
          </Widget>
        )}
        {costs.length > 0 && (
          <Widget title="Costs by category" count={costs.length} to="/ledger">
            {costs.map((r) => (
              <div key={r.key} className="wrow cost">
                <span className="grow">{words(r.key)}<span className="bar" style={{ width: `${Math.max(4, (Math.abs(Number(r.amount_base.amount)) / biggest) * 100)}%` }} /></span>
                {typeof r.change_pct === "number" && <span className={`caption ${r.change_pct > 0 ? "danger" : "muted"}`}>{r.change_pct > 0 ? "+" : ""}{r.change_pct}%</span>}
                <span className="medium amount">{formatMoney(r.amount_base, { decimals: false })}</span>
              </div>
            ))}
          </Widget>
        )}
        {fx.length > 0 && (
          <Widget title="Currency risk" count={fx.length}>
            {fx.map((x) => {
              const hedge = x.verdict === "hedge_proposed";
              return (
                <div key={x.document_id ?? x.recommendation_id} className="wrow">
                  <span className="grow">
                    {formatMoney(x.amount, { decimals: false })}
                    {x.expected_shortfall && <span className="caption muted"> · a bad rate could cost {formatMoney(x.expected_shortfall, { decimals: false }).replace("-", "")}{x.deal_profit ? ` of ${formatMoney(x.deal_profit, { decimals: false })} profit` : ""}</span>}
                  </span>
                  {x.recommendation_id
                    ? <Link to={`/inbox/${x.recommendation_id}`} className={`chip ${hedge ? "warning" : "neutral"}`}>{hedge ? "Protect it" : "No need to protect"}</Link>
                    : <span className="chip neutral">{words(x.verdict)}</span>}
                </div>
              );
            })}
          </Widget>
        )}
        <Widget title="Accounts" count={accounts.items.length} to="/transactions">
          {accounts.items.map((a) => (
            <Link key={a.id} to={`/accounts/${a.id}`} className="wrow rowlink">
              <span className="grow">{a.name}{!a.include_in_liquidity && <span className="caption muted"> · not company cash</span>}</span>
              <span className="medium amount">{a.balance ? formatMoney(a.balance) : "—"}</span>
            </Link>
          ))}
        </Widget>
      </div>

      {(forecast || notes.length > 0) && (
        <div className="card">
          <MoreGroup>
            {forecast && (
              <More title="What the forecast assumes" count={forecast.assumptions.length}>
                {forecast.assumptions.map((a) => <p key={a} className="tertiary">{a}</p>)}
              </More>
            )}
            {forecast && (
              <More title="Balance day by day" count={dailyBalances(forecast).length}>
                <table className="plain-table">
                  <tbody>{dailyBalances(forecast).map((d) => <tr key={d.date}><td className="tertiary">{shortDate(d.date)}</td><td className={`right${isNegative(d.balance) ? " danger" : ""}`}>{formatMoney(d.balance, { decimals: false })}</td></tr>)}</tbody>
                </table>
              </More>
            )}
            {notes.length > 0 && (
              <More title="Data notes" count={notes.length}>
                {notes.map((n) => <div key={n.text} className="calc-row"><div className="grow">{n.text}</div><Evidence links={[n.evidence]} /></div>)}
              </More>
            )}
          </MoreGroup>
        </div>
      )}
    </>
  );
}

function Tile({ label, value, sub, to }: { label: string; value: string; sub?: string; to?: string }) {
  const body = <><div className="tertiary">{label}</div><div className="tile-value">{value}</div>{sub && <div className="small muted">{sub}</div>}</>;
  return to ? <Link to={to} className="card tile link">{body}</Link> : <div className="card tile">{body}</div>;
}

function Widget({ title, count, to, children }: { title: string; count?: number; to?: string; children: ReactNode }) {
  return (
    <section className="card widget">
      <div className="hstack">
        <span className="tertiary grow">{title}{count !== undefined && <span className="muted"> {count}</span>}</span>
        {to && <Link to={to} className="small">See all</Link>}
      </div>
      <div>{children}</div>
    </section>
  );
}
