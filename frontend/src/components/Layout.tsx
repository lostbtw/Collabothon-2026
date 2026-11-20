import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { API_MODE } from "../config";
import { useCompany } from "../lib/company";
import { useApi } from "../lib/useApi";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/inbox", label: "Inbox" },
  { to: "/documents", label: "Documents" },
  { to: "/sources", label: "Sources" },
  { to: "/activity", label: "Activity" },
  { to: "/chat", label: "Chat" },
];

export function Layout() {
  const { companyId, setCompanyId } = useCompany();
  const companies = useApi(() => api.companies(), []);
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Ordo</div>
        <div className="company">
          <label htmlFor="company">Company</label>
          <select id="company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            {(companies.data?.items ?? [{ id: companyId, name: companyId }]).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <nav className="stack" style={{ gap: 4 }}>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>{n.label}</NavLink>
          ))}
        </nav>
        <div className="mode">Data: <strong>{API_MODE === "mock" ? "mock (fixtures)" : "live API"}</strong></div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
