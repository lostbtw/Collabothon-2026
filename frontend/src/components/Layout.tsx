import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { API_MODE } from "../config";
import { useCompany } from "../lib/company";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { companyLines } from "../lib/words";
import { buildTodo } from "../pages/todo/model";
import { AskProvider } from "./AskOrdo";
import { Icon } from "./Icon";
import { Toasts } from "./Toasts";

/** The shell: three places and Settings on the left, the page on the right, Ask Ordo over everything. */
export function Layout() {
  const { companyId, setCompanyId, companies } = useCompany();
  const refresh = useRefreshKey();
  const todo = useApi(() => Promise.all([api.inbox(companyId), api.forecast(companyId).catch(() => null)]), [companyId, refresh]);
  const count = todo.data ? buildTodo(todo.data[0].items, todo.data[1]).count : null;
  const company = companies?.find((c) => c.id === companyId);
  const lines = companyLines(company?.name ?? companyId);

  return (
    <AskProvider>
      <div className="app">
        <aside className="sidebar">
          <div className="brand"><span className="logo">O</span><span className="heading">Ordo</span></div>
          <label className="company">
            <span className="medium">{lines.main}</span>
            <span className="small t3">{lines.sub}</span>
            {companies && companies.length > 1 && (
              <>
                <select aria-label="Company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
                  {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <span className="company-chev"><Icon name="chevron" size={14} /></span>
              </>
            )}
          </label>
          <nav className="stack" style={{ gap: 4 }} aria-label="Main">
            <NavLink to="/" end className={navClass}>Overview</NavLink>
            <NavLink to="/money" className={navClass}>Money</NavLink>
            <NavLink to="/todo" className={navClass}>To-do{count ? <span className="nav-count">{count}</span> : null}</NavLink>
          </nav>
          <span className="grow" />
          <NavLink to="/settings" className={navClass}>Settings</NavLink>
          {/* Switching data is still possible with ?mock=1 or ?mock=0 in the address; the owner does not need a button. */}
          <p className="sidebar-note">{API_MODE === "mock" ? "Sample data" : "Live data"} · every action is simulated</p>
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

const navClass = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;
