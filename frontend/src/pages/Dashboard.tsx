import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { formatMoney, isNegative } from "../lib/money";
import { useApi } from "../lib/useApi";

export function Dashboard() {
  const { companyId } = useCompany();
  const state = useApi(() => Promise.all([api.accounts(companyId), api.forecast(companyId), api.ledgerSummary(companyId)]), [companyId]);
  return (
    <>
      <h1>Dashboard</h1>
      <PageState state={state}>
        {([accounts, forecast, summary]) => (
          <>
            <div className="row">
              <div className="card"><p className="muted small">Cash today</p><p className="kpi-value">{formatMoney(accounts.total_liquidity_base, { decimals: false })}</p><p className="muted small">Across {accounts.items.filter((a) => a.include_in_liquidity).length} company accounts</p></div>
              <div className="card"><p className="muted small">Lowest point</p><p className={`kpi-value${isNegative(forecast.min_balance.amount) ? " danger" : ""}`}>{formatMoney(forecast.min_balance.amount, { decimals: false })}</p><p className="muted small">On {forecast.min_balance.date}{forecast.first_negative_date ? `; below zero from ${forecast.first_negative_date}` : ""}</p></div>
              <div className="card"><p className="muted small">Owed to employees</p><p className="kpi-value">{formatMoney(summary.kpis.reimbursements_owed, { decimals: false })}</p><p className="muted small">VAT lost this year: {formatMoney(summary.kpis.vat_lost_ytd)}</p></div>
            </div>
            <div className="card">
              <h2>What the {forecast.horizon_days}-day forecast is made of</h2>
              <ul className="plain">
                {forecast.components.map((c) => (
                  <li key={c.id}>{c.label}: <strong>{formatMoney(c.amount_base, { decimals: false })}</strong>{c.schedule ? <span className="muted"> ({c.schedule})</span> : null}</li>
                ))}
              </ul>
            </div>
          </>
        )}
      </PageState>
    </>
  );
}
