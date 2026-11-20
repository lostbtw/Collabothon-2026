import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type ActivityItem, type DocumentDetail } from "../api/client";
import type { Match, OrdoDocument } from "../api/types.gen";
import { ControlBadges } from "../components/ControlBadges";
import { Evidence } from "../components/More";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { dateTime } from "../lib/dates";
import { useLive } from "../lib/live";
import { useApi } from "../lib/useApi";

export const CHANNEL_LABEL: Record<OrdoDocument["channel"], string> = { ksef: "E-invoice (XML)", email: "PDF by e-mail", photo: "Photo", accounting_api: "Accounting tool", upload: "Upload" };

export type ActivityDetail = { kind: "document"; data: DocumentDetail } | { kind: "match"; match: Match } | null;

/** What stands behind one feed line: the merged copies of a document, or the reasons of a match. */
export async function loadDetail(item: ActivityItem): Promise<ActivityDetail> {
  if (item.subject?.type === "document") return { kind: "document", data: await api.document(item.subject.id) };
  if (item.subject?.type === "match") {
    const match = (await api.matches()).items.find((m) => m.id === item.subject!.id);
    return match ? { kind: "match", match } : null;
  }
  return null;
}

export function Activity() {
  const { companyId } = useCompany();
  const [reload, setReload] = useState(0);
  const state = useApi(() => api.activity(companyId), [companyId, reload]);
  useLive((e) => { if (e.type === "match.suggested" || e.type === "document.extracted" || e.type === "match.decided") setReload((n) => n + 1); });

  // Undo of an automatic match = reject it; the line then leaves the feed.
  async function undo(item: ActivityItem) {
    await api.decideMatch(item.subject!.id, { decision: "rejected", channel: "dashboard" });
    setReload((n) => n + 1);
  }
  return (
    <>
      <div className="hstack"><h1>What I did on my own</h1><ControlBadges level="analysed_autonomously" /></div>
      <PageState state={state} keepWhileLoading empty={(d) => d.items.length === 0}>
        {(activity) => <ActivityView items={activity.items} onUndo={undo} />}
      </PageState>
    </>
  );
}

export function ActivityView({ items, onUndo, open }: { items: ActivityItem[]; onUndo: (item: ActivityItem) => Promise<void>; open?: Record<string, ActivityDetail> }) {
  return (
    <div className="card feed">
      {items.map((a) => <Line key={a.at + a.text} item={a} onUndo={onUndo} preloaded={open?.[a.at]} />)}
    </div>
  );
}

function Line({ item, onUndo, preloaded }: { item: ActivityItem; onUndo: (item: ActivityItem) => Promise<void>; preloaded?: ActivityDetail }) {
  const [open, setOpen] = useState(Boolean(preloaded));
  const [detail, setDetail] = useState<ActivityDetail | undefined>(preloaded);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canUndo = item.subject?.type === "match";

  async function toggle() {
    setOpen(!open);
    if (!open && detail === undefined) setDetail(await loadDetail(item).catch(() => null));
  }
  async function undo() {
    setBusy(true);
    setError(null);
    try {
      await onUndo(item);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }
  return (
    <div className="feed-line">
      <div className="feed-main">
        <span className="small muted feed-time">{dateTime(item.at).split(", ")[1]}</span>
        <span className="grow">{item.text}</span>
        {item.subject && <button type="button" className="outline" aria-expanded={open} onClick={toggle}>{open ? "Hide" : "Details"}</button>}
        {canUndo && <button type="button" className="outline" disabled={busy} onClick={undo}>{busy ? "Undoing…" : "Undo"}</button>}
      </div>
      {error && <p className="small danger feed-detail" role="alert">Not undone: {error}</p>}
      {open && (
        <div className="feed-detail stack">
          {detail === undefined && <p className="small muted">Loading…</p>}
          {detail?.kind === "document" && detail.data.duplicates.length > 0 && (
            <>
              <p className="medium">{detail.data.duplicates.length + 1} copies → one record</p>
              <div className="hstack">{[detail.data.document, ...detail.data.duplicates].map((c) => <span key={c.id} className="chip neutral">{CHANNEL_LABEL[c.channel]}</span>)}</div>
            </>
          )}
          {detail?.kind === "match" && <ol className="reasons">{detail.match.reasons.map((r, i) => <li key={r.rule} className="reason"><span className="reason-n">{i + 1}</span><span>{r.detail}</span></li>)}</ol>}
          {item.evidence.length > 0 && <Evidence links={item.evidence} />}
          {detail === null && item.evidence.length === 0 && <p className="small muted">Nothing more to show.</p>}
        </div>
      )}
      {!item.subject && item.evidence.some((e) => e.url) && <Link to={item.evidence.find((e) => e.url)!.url!} className="small feed-detail">{item.evidence.find((e) => e.url)!.label}</Link>}
    </div>
  );
}
