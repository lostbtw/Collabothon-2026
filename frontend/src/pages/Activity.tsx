// Activity: one log of everything that happened, what the owner decided and what Ordo did on its own, by day.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Icon } from "../components/Icon";
import { PageHead, Skeleton, Tile } from "../components/ui";
import { useCompany, useToday } from "../lib/company";
import { daysBetween, longDate } from "../lib/dates";
import { useLive } from "../lib/live";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { DoneModal, LogLine, titleOf } from "./todo/done";
import { byDay, ordoLog, ownerLog, undoKind, type Done } from "./todo/model";

export { CHANNEL_LABEL, loadDetail, type ActivityDetail } from "./todo/done";

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
type Show = "all" | "you" | "ordo";

export function Activity() {
  const { companyId } = useCompany();
  const today = useToday();
  const refresh = useRefreshKey();
  const [reload, setReload] = useState(0);
  const state = useApi(() => Promise.all([
    api.activity(companyId), none(api.approvals(companyId)),
    none(api.recommendations(companyId, "executed_simulated")), none(api.recommendations(companyId, "rejected")),
  ]), [companyId, refresh, reload]);
  useLive((e) => { if (e.type === "match.suggested" || e.type === "document.extracted" || e.type === "match.decided") setReload((n) => n + 1); });
  const head = <PageHead title="Activity" sub="Everything that happened: what you decided, and what Ordo did on its own." ><Link to="/todo" className="button">Back to To-do</Link></PageHead>;
  if (state.loading && !state.data) return <>{head}<Skeleton tiles={3} rows={6} /></>;
  if (state.error) return <>{head}<p className="bad" role="alert">Could not load the activity: {state.error}</p></>;
  const [activity, approvals, executed, rejected] = state.data!;
  const lines = [...ownerLog(approvals?.items ?? [], [...(executed?.items ?? []), ...(rejected?.items ?? [])]), ...ordoLog(activity.items)];
  return <>{head}<ActivityView lines={lines} today={today} /></>;
}

export function ActivityView({ lines, today }: { lines: Done[]; today: string }) {
  const [show, setShow] = useState<Show>("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Done | null>(null);
  const mine = lines.filter((d) => d.level === "approved");
  const ordo = lines.filter((d) => d.level === "analysed_autonomously");
  const undoable = lines.filter((d) => undoKind(d) !== null).length;
  const needle = q.trim().toLowerCase();
  const shown = (show === "you" ? mine : show === "ordo" ? ordo : lines)
    .filter((d) => !needle || [titleOf(d), d.text, d.reference ?? ""].some((s) => s.toLowerCase().includes(needle)));
  const tabs: [Show, string, number][] = [["all", "All", lines.length], ["you", "By you", mine.length], ["ordo", "By Ordo", ordo.length]];
  return (
    <>
      <div className="row">
        <Tile label="You decided" value={mine.length} note={`${mine.filter((d) => !d.saidNo).length} approved · ${mine.filter((d) => d.saidNo).length} said no`} />
        <Tile label="Ordo did on its own" value={ordo.length} />
        <Tile label="Can be undone" value={undoable} note={undoable ? "Open a line to undo it" : "Nothing to undo"} />
      </div>
      <div className="stack" style={{ gap: 20 }}>
        <div className="toolbar">
          <div className="tabs" role="tablist" aria-label="Show">
            {tabs.map(([key, label, n]) => (
              <button key={key} type="button" role="tab" aria-selected={show === key} className={show === key ? "on" : undefined} onClick={() => setShow(key)}>
                {label}<span className="tab-count">{n}</span>
              </button>
            ))}
          </div>
          <span className="grow" />
          <label className="search"><Icon name="search" size={16} /><input type="search" placeholder="Search the log" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the log" /></label>
        </div>
        {shown.length === 0 && <div className="card t2">{needle ? "Nothing matches your search." : show === "you" ? "You have not decided anything yet." : "Nothing here yet."}</div>}
        {byDay(shown).map(([day, items]) => (
          <section key={day} className="day-group">
            <div className="day-head"><span className="medium">{dayName(day, today)}</span><span className="small t3">{items.length} {items.length === 1 ? "event" : "events"}</span></div>
            <div className="card log-card"><ol className="timeline">{items.map((d) => <LogLine key={d.at + d.text} d={d} onOpen={setOpen} full />)}</ol></div>
          </section>
        ))}
      </div>
      {open && <DoneModal done={open} onClose={() => setOpen(null)} />}
    </>
  );
}

/** "Today", "Yesterday", or the date. */
function dayName(day: string, today: string): string {
  const diff = daysBetween(day, today);
  return diff === 0 ? `Today · ${longDate(day)}` : diff === 1 ? `Yesterday · ${longDate(day)}` : longDate(day);
}
