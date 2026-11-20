import { Link } from "react-router-dom";
import { api, type AccountsResponse, type InboxResponse, type LedgerSummary } from "../api/client";
import type { Forecast } from "../api/types.gen";
import { ForecastChart } from "../components/ForecastChart";
import { Icon } from "../components/Icon";
import { More, MoreGroup } from "../components/More";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { formatMoney, isNegative } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { weather } from "./dashboard/model";

export function Dashboard() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  // Cash and forecast must load; the other two only add a number and a button.
  const state = useApi(
    () => Promise.all([api.accounts(companyId), api.forecast(companyId), api.ledgerSummary(companyId).catch(() => null), api.inbox(companyId).catch(() => null)]),
    [companyId, refresh],
  );
  return (
    <PageState state={state} keepWhileLoading>
      {([accounts, forecast, summary, inbox]) => <DashboardView accounts={accounts} forecast={forecast} summary={summary} inbox={inbox} />}
    </PageState>
  );
}

export function DashboardView({ accounts, forecast, summary, inbox, flash }: { accounts: AccountsResponse; forecast: Forecast; summary: LedgerSummary | null; inbox: InboxResponse | null; flash?: boolean }) {
  const w = weather(forecast);
  const fix = inbox?.items.find((r) => r.agent === "liquidity" && r.control_level === "approval_required");
  const cash = accounts.items.filter((a) => a.include_in_liquidity && a.balance);
  const low = forecast.min_balance;
  return (
    <>
      <div className="hstack"><h1>Home</h1><span className="muted">as of {shortDate(forecast.as_of_date)}</span></div>
      <div className="row">
        <div className="card stack" style={{ gap: 4 }}>
          <div className="tertiary">Cash today</div>
          <div className="display">{formatMoney(accounts.total_liquidity_base ?? forecast.opening_balance, { decimals: false })}</div>
          <div className="small muted">{cash.map((a) => formatMoney(a.balance)).join(" + ")}</div>
        </div>
        <div className={`card stack weather ${w.kind}`} style={{ gap: 4 }}>
          <div className="hstack tertiary"><Icon name={({ storm: "storm", cloudy: "cloud", sunny: "sun" } as const)[w.kind]} size={18} />Cash weather</div>
          <div className="display">{w.headline}</div>
          <div className="hstack">
            <span className={`small ${isNegative(low.amount) ? "danger" : "muted"}`}>Lowest {formatMoney(low.amount, { decimals: false })} on {shortDate(low.date)}</span>
            <span className="grow" />
            {fix && <Link to={`/inbox/${fix.id}`} className="button primary">See the fix</Link>}
          </div>
        </div>
        {summary && (
          <div className="card stack" style={{ gap: 4 }}>
            <div className="tertiary">Owed to the team</div>
            <div className="display">{formatMoney(summary.kpis.reimbursements_owed, { decimals: false })}</div>
            <div className="small muted">not visible on the bank account</div>
          </div>
        )}
      </div>
      <div className="card stack">
        <div className="tertiary">Next {forecast.horizon_days} days</div>
        <ForecastChart forecast={forecast} flash={flash} />
        <MoreGroup>
          <More title="What moves your cash" count={forecast.components.length}>
            {forecast.components.map((c) => {
              const source = (c.evidence ?? []).map((e) => e.label).join(", ");
              const to = c.evidence?.find((e) => e.url)?.url;
              const row = (
                <>
                  <div className="grow"><div>{c.label}</div><div className="caption muted">{(c.dates ?? []).map((d) => shortDate(d)).join(", ")}{source ? ` · source: ${source}` : ""}</div></div>
                  <div className={`medium right${isNegative(c.amount_base) ? "" : " positive"}`}>{formatMoney(c.amount_base, { decimals: false })}</div>
                </>
              );
              return to ? <Link key={c.id} to={to} className="calc-row rowlink" title={`Source: ${source}. Click to open the rows.`}>{row}</Link> : <div key={c.id} className="calc-row" title={source ? `Source: ${source}` : undefined}>{row}</div>;
            })}
          </More>
          <More title="Assumptions" count={forecast.assumptions.length}>
            {forecast.assumptions.map((a) => <p key={a} className="tertiary">{a}</p>)}
          </More>
          <More title="Day by day" count={forecast.points.length}>
            <table className="plain-table">
              <tbody>{forecast.points.map((p) => <tr key={p.date}><td className="tertiary">{shortDate(p.date)}</td><td className={`right${p.balance.startsWith("-") ? " danger" : ""}`}>{formatMoney({ amount: p.balance, currency: forecast.base_currency }, { decimals: false })}</td></tr>)}</tbody>
            </table>
          </More>
        </MoreGroup>
      </div>
    </>
  );
}
