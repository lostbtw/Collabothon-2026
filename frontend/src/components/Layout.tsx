import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { API_MODE } from "../config";
import { useCompany } from "../lib/company";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { companyLines, initials } from "../lib/words";
import { buildTodo } from "../pages/todo/model";
import { AskProvider } from "./AskOrdo";
import { Icon, type IconName } from "./Icon";
import { Toasts } from "./Toasts";

const FOLDED_KEY = "ordo.sidebar.folded";
const savedFolded = (): boolean => { try { return window.localStorage.getItem(FOLDED_KEY) === "1"; } catch { return false; } };

export function Layout() {
  const { companyId, setCompanyId, companies } = useCompany();
  const refresh = useRefreshKey();
  const [folded, setFolded] = useState(savedFolded);
  const todo = useApi(() => Promise.all([api.inbox(companyId), api.forecast(companyId).catch(() => null)]), [companyId, refresh]);
  const count = todo.data ? buildTodo(todo.data[0].items, todo.data[1]).count : null;
  const company = companies?.find((c) => c.id === companyId);
  const lines = companyLines(company?.name ?? companyId);
  function fold() {
    setFolded(!folded);
    try { window.localStorage.setItem(FOLDED_KEY, folded ? "0" : "1"); } catch { /* lasts until reload */ }
  }
  const note = `${API_MODE === "mock" ? "Sample data" : "Live data"} · every action is simulated`;

  return (
    <AskProvider>
      <div className={`app${folded ? " folded" : ""}`}>
        <aside className="sidebar">
          <div className="brand">
            <span className="logo">O</span><span className="heading brand-name">Ordo</span>
            <button type="button" className="quiet icon-button fold" onClick={fold} aria-label={folded ? "Open the menu" : "Fold the menu"} aria-expanded={!folded} title={folded ? "Open the menu" : "Fold the menu"}>
              <Icon name={folded ? "chevronRight" : "chevronLeft"} size={16} />
            </button>
          </div>
          <label className="company" title={folded ? company?.name : undefined}>
            {folded ? <span className="avatar">{initials(lines.main)}</span> : (
              <>
                <span className="medium">{lines.main}</span>
                <span className="small t3">{lines.sub}</span>
              </>
            )}
            {companies && companies.length > 1 && (
              <>
                <select aria-label="Company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
                  {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                {!folded && <span className="company-chev"><Icon name="chevron" size={14} /></span>}
              </>
            )}
          </label>
          <nav className="stack" style={{ gap: 4 }} aria-label="Main">
            <NavItem to="/" end icon="home" label="Overview" folded={folded} />
            <NavItem to="/money" icon="swap" label="Finances" folded={folded} />
            <NavItem to="/todo" icon="check" label="To-do" folded={folded} count={count} />
          </nav>
          <span className="grow" />
          <NavItem to="/settings" icon="gear" label="Settings" folded={folded} />
          {folded ? <span className="sidebar-note folded-note" title={note}>Sim</span> : <p className="sidebar-note">{note}</p>}
        </aside>
        <main className="main">
          <div className="main-inner">
            <Outlet />
          </div>
        </main>
        <Toasts />
      </div>
    </AskProvider>
  );
}

function NavItem({ to, end, icon, label, folded, count }: { to: string; end?: boolean; icon: IconName; label: string; folded: boolean; count?: number | null }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} title={folded ? label : undefined} aria-label={folded ? label : undefined}>
      <span className="nav-icon"><Icon name={icon} size={18} />{folded && count ? <span className="nav-dot">{count}</span> : null}</span>
      {!folded && <span className="grow">{label}</span>}
      {!folded && count ? <span className="nav-count">{count}</span> : null}
    </NavLink>
  );
}
