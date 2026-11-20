import { Link, NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { API_MODE } from "../config";
import { useCompany } from "../lib/company";
import { daysBetween } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { Icon, type IconName } from "./Icon";

const NAV: { to: string; label: string; icon: IconName; end?: boolean; count?: "inbox" | "documents" }[] = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/inbox", label: "Inbox", icon: "inbox", count: "inbox" },
  { to: "/documents", label: "Documents", icon: "file", count: "documents" },
  { to: "/transactions", label: "Transactions", icon: "swap" },
  { to: "/ledger", label: "Ledger", icon: "book" },
  { to: "/sources", label: "Sources", icon: "plug" },
  { to: "/activity", label: "Activity", icon: "pulse" },
  { to: "/chat", label: "Ask Ordo", icon: "chat" },
];

export function Layout() {
  const { companyId, setCompanyId } = useCompany();
  const refresh = useRefreshKey();
  const companies = useApi(() => api.companies(), []);
  const sources = useApi(() => api.sources(companyId), [companyId, refresh]);
  const inbox = useApi(() => api.inbox(companyId), [companyId, refresh]);
  const toReview = useApi(() => api.documents(companyId, { status: "needs_review" }), [companyId, refresh]);
  const forecast = useApi(() => api.forecast(companyId), [companyId, refresh]);
  const summary = useApi(() => api.ledgerSummary(companyId), [companyId, refresh]);

  const counts = { inbox: inbox.data?.counts.approval_required, documents: toReview.data?.items.length };
  const sourceItems = sources.data?.items ?? [];
  const unhealthy = sourceItems.filter((s) => s.status === "error" || s.status === "degraded").length;
  const hedges = inbox.data?.items.filter((r) => r.agent === "fx" && r.type === "fx_hedge").length ?? 0;
  const gapIn = forecast.data?.first_negative_date ? daysBetween(forecast.data.as_of_date, forecast.data.first_negative_date) : null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="switcher">
          <span className="logo">O</span>
          <select aria-label="Company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            {(companies.data?.items ?? [{ id: companyId, name: companyId }]).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <Icon name="chevron" size={14} />
        </div>
        <Link to="/chat" className="search"><Icon name="search" size={15} />Search or ask Ordo anything</Link>
        <span className="grow" />
        {sources.data && (
          <Link to="/sources" className="sync">
            <span className={`dot${unhealthy ? " degraded" : ""}`} style={{ marginRight: 0 }} />
            {sourceItems.length} sources · {unhealthy ? `${unhealthy} need attention` : "all connected"}
          </Link>
        )}
        <span className="chip">Sandbox · actions are simulated</span>
        <span className="avatar" title="Owner"><Icon name="user" /></span>
      </header>
      <div className="body">
        <aside className="sidebar">
          <nav className="stack" style={{ gap: 4 }} aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} title={n.label}>
                <Icon name={n.icon} />
                <span className="label">{n.label}</span>
                {n.count && counts[n.count] ? <span className="nav-count">{counts[n.count]}</span> : null}
              </NavLink>
            ))}
          </nav>
          <div className="nav-section">Agents</div>
          <Agent icon="drop" name="Liquidity" tone={gapIn !== null ? "danger" : undefined}
            status={!forecast.data ? "…" : gapIn === null ? `No gap in the next ${forecast.data.horizon_days} days` : gapIn <= 0 ? "Cash gap now" : `Cash gap in ${gapIn} days`} />
          <Agent icon="shield" name="FX Shield" tone={hedges ? "accent" : undefined}
            status={!inbox.data ? "…" : hedges ? `${hedges} hedge${hedges > 1 ? "s" : ""} proposed` : "Nothing to hedge"} />
          <Agent icon="percent" name="Tax"
            status={!summary.data ? "…" : `${formatMoney(summary.data.kpis.tax_due_next_30d, { decimals: false })} due in 30 days`} />
          <div className="mode">Data: {API_MODE === "mock" ? "sample data (mock mode)" : "live API"}</div>
        </aside>
        <main className="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Agent({ icon, name, status, tone }: { icon: IconName; name: string; status: string; tone?: "danger" | "accent" }) {
  return (
    <div className="agent">
      <Icon name={icon} />
      <div>
        <div>{name}</div>
        <div className={`agent-status${tone ? ` ${tone}` : ""}`}>{status}</div>
      </div>
    </div>
  );
}
