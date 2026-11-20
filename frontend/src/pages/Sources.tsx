import { useState } from "react";
import { api } from "../api/client";
import type { Source } from "../api/types.gen";
import { PageState } from "../components/PageState";
import { ago, useNow } from "../lib/clock";
import { useCompany } from "../lib/company";
import { useLive } from "../lib/live";
import { requestRefresh, useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";

export function Sources() {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const [reload, setReload] = useState(0);
  const now = useNow();
  const state = useApi(() => api.sources(companyId), [companyId, reload, refresh]);
  // A finished sync changes "last synced" and the counters: re-read without a page reload.
  useLive((e) => { if (e.type === "sync.run.finished") setReload((n) => n + 1); });

  async function sync(id: string) {
    await api.syncNow(id);
    setReload((n) => n + 1);
    requestRefresh();
  }
  return (
    <>
      <h1>Sources</h1>
      <PageState state={state} keepWhileLoading empty={(d) => d.items.length === 0}>
        {(sources) => <SourcesView sources={sources.items} now={now} onSync={sync} />}
      </PageState>
    </>
  );
}

export function SourcesView({ sources, now, onSync }: { sources: Source[]; now: number | null; onSync: (id: string) => Promise<void> }) {
  return (
    <div className="card table-card">
      <table>
        <thead><tr><th>Source</th><th>Last synced</th><th className="right">Items</th><th /></tr></thead>
        <tbody>{sources.map((s) => <Row key={s.id} s={s} now={now} onSync={onSync} />)}</tbody>
      </table>
    </div>
  );
}

function Row({ s, now, onSync }: { s: Source; now: number | null; onSync: (id: string) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unhealthy = s.status === "degraded" || s.status === "error";
  async function run() {
    setBusy(true);
    setError(null);
    try {
      await onSync(s.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <tr className={`source ${s.status}`}>
      <td>
        <span className={`dot ${s.status}`} />{s.display_name}
        {s.status !== "connected" && <span className={`chip ${s.status === "error" ? "danger" : "warning"}`} style={{ marginLeft: 8 }}>{s.status}</span>}
        {unhealthy && s.last_error && <div className="small tertiary" style={{ marginLeft: 15 }}>{s.last_error.message}</div>}
        {error && <div className="small danger" role="alert" style={{ marginLeft: 15 }}>Sync did not start: {error}</div>}
      </td>
      <td className="tertiary">{!s.last_synced_at ? "never" : now === null ? "…" : ago(s.last_synced_at, now)}</td>
      <td className="right">{s.items_total ?? "—"}</td>
      <td className="right"><button type="button" className="outline" disabled={busy || s.status === "paused"} onClick={run}>{busy ? "Syncing…" : "Sync now"}</button></td>
    </tr>
  );
}
