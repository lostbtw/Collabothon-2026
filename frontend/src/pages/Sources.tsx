import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { useApi } from "../lib/useApi";

export function Sources() {
  const { companyId } = useCompany();
  const state = useApi(() => api.sources(companyId), [companyId]);
  return (
    <>
      <div><h1>Sources</h1><p className="muted">Nothing here was uploaded. Each source is checked on its own schedule.</p></div>
      <PageState state={state} empty={(d) => d.items.length === 0}>
        {(sources) => (
          <div className="card table-card">
            <table>
              <thead><tr><th>Source</th><th>Status</th><th>Last synced</th><th>Items</th></tr></thead>
              <tbody>
                {sources.items.map((s) => (
                  <tr key={s.id}>
                    <td><strong>{s.display_name}</strong>{s.last_error ? <div className="muted small">{s.last_error.message}</div> : null}</td>
                    <td><span className={`dot ${s.status}`} />{s.status}</td>
                    <td>{s.last_synced_at ? new Date(s.last_synced_at).toLocaleString("en-GB", { timeZone: "UTC" }) + " UTC" : "never"}</td>
                    <td>{s.items_total ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageState>
    </>
  );
}
