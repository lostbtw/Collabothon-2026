// To-do: only what the owner decides. Every action runs only after a yes, and only in the sandbox.
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, type ActivityItem, type LedgerSummary, type PeopleCosts } from "../api/client";
import type { Approval, Forecast, Recommendation } from "../api/types.gen";
import { Icon } from "../components/Icon";
import { DoneChip, PageHead, SimButton, Skeleton, StatusLabel } from "../components/ui";
import { lastFullMonth, monthFigures, monthOnly, monthRange, percent } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { shortDate } from "../lib/dates";
import { useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { whole } from "../lib/words";
import { canApprove } from "./inbox/model";
import { Added, RecModal, Result, useDecision } from "./todo/details";
import { DoneModal, LogLine } from "./todo/done";
import { approveLabel, buildTodo, costLabel, doneRecently, isTodoSort, sortTodo, TODO_SORTS, type Done, type TodoItem, type TodoSort } from "./todo/model";

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
const HIDDEN_KEY = "ordo.todo.notNow";
const SORT_KEY = "ordo.todo.sort";
const hiddenNow = (): string[] => { try { return JSON.parse(window.sessionStorage.getItem(HIDDEN_KEY) ?? "[]") as string[]; } catch { return []; } };
const savedSort = (): TodoSort => { try { const s = window.localStorage.getItem(SORT_KEY); return isTodoSort(s) ? s : "newest"; } catch { return "newest"; } };

export function Todo() {
  const { companyId } = useCompany();
  const today = useToday();
  const refresh = useRefreshKey();
  const month = lastFullMonth(today);
  const state = useApi(() => Promise.all([
    api.inbox(companyId), none(api.forecast(companyId)), none(api.recommendations(companyId, "executed_simulated")), none(api.approvals(companyId)), none(api.activity(companyId)),
  ]), [companyId, refresh]);
  const close = useApi(() => Promise.all([
    none(api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month) })), none(api.peopleCosts(companyId, month)),
  ]), [companyId, month, refresh]);

  if (state.loading && !state.data) return <><PageHead title="To-do" sub="Only you can decide these. Nothing happens until you say yes." /><Skeleton rows={5} title /><Skeleton rows={3} /></>;
  if (state.error) return <><PageHead title="To-do" /><p className="bad" role="alert">Could not load To-do: {state.error}</p></>;
  const [inbox, forecast, recs, approvals, activity] = state.data!;
  const [summary, people] = close.data ?? [null, null];
  return (
    <TodoView items={inbox.items} forecast={forecast} recs={recs?.items ?? inbox.items} approvals={approvals?.items ?? []} activity={activity?.items ?? []}
      month={month} summary={summary} people={people} />
  );
}

type ViewProps = {
  items: Recommendation[]; forecast: Forecast | null; recs: Recommendation[]; approvals: Approval[]; activity: ActivityItem[];
  month: string; summary: LedgerSummary | null; people: PeopleCosts | null;
};
type Show = "all" | "ok" | "check";

export function TodoView({ items, forecast, recs, approvals, activity, month, summary, people }: ViewProps) {
  const { hash } = useLocation();
  const [hidden, setHidden] = useState<string[]>(hiddenNow);
  const [sort, setSort] = useState<TodoSort>(savedSort);
  const [show, setShow] = useState<Show>("all");
  const todo = buildTodo(items, forecast);
  const gap = todo.needsOk.find((i) => i.gap && !hidden.includes(i.id)) ?? null;
  const needsOk = todo.needsOk.filter((i) => !i.gap);
  const list = sortTodo(show === "ok" ? needsOk : show === "check" ? todo.check : [...needsOk, ...todo.check], sort);
  const target = decodeURIComponent(hash.replace(/^#/, ""));
  useEffect(() => { if (target) document.getElementById(target)?.scrollIntoView?.({ block: "center" }); }, [target]);
  function notNow(id: string) {
    const next = [...hidden, id];
    setHidden(next);
    try { window.sessionStorage.setItem(HIDDEN_KEY, JSON.stringify(next)); } catch { /* the choice lasts until reload */ }
  }
  function chooseSort(s: TodoSort) {
    setSort(s);
    try { window.localStorage.setItem(SORT_KEY, s); } catch { /* the choice lasts until reload */ }
  }
  const okCount = needsOk.length + (gap ? 1 : 0);
  const tabs: [Show, string, number][] = [["all", "All", okCount + todo.check.length], ["ok", "Needs your confirmation", okCount], ["check", "To check", todo.check.length]];
  return (
    <>
      <PageHead title="To-do" sub="Only you can decide these. Nothing happens until you say yes." />
      <div className="todo-cols">
        <div className="stack" style={{ gap: 16 }}>
          <div className="toolbar">
            <div className="tabs" role="tablist" aria-label="Show">
              {tabs.map(([key, label, n]) => (
                <button key={key} type="button" role="tab" aria-selected={show === key} className={show === key ? "on" : undefined} onClick={() => setShow(key)}>
                  {label}<span className="tab-count">{n}</span>
                </button>
              ))}
            </div>
            <span className="grow" />
            <label className="pill-select" title={TODO_SORTS.find((s) => s.key === sort)?.hint}>
              <span className="pill-label"><span className="t3" style={{ fontWeight: 400 }}>Sort:&nbsp;</span>{TODO_SORTS.find((s) => s.key === sort)?.label}</span>
              <select aria-label="Sort" value={sort} onChange={(e) => chooseSort(e.target.value as TodoSort)}>
                {TODO_SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
              <Icon name="chevron" size={14} />
            </label>
          </div>
          {gap && show !== "check" && <GapCard item={gap} onNotNow={() => notNow(gap.id)} target={target} />}
          {list.length === 0 && !(gap && show !== "check") ? (
            <div className="card t2">{show === "check" ? "Nothing to check." : "Nothing waits for your confirmation."}{hidden.length ? " Some items are hidden until you reload the page." : ""}</div>
          ) : list.length > 0 && (
            <div className="card todo-list">
              {list.map((item) => <TodoRow key={item.id} item={item} sort={sort} open={target === item.id} />)}
            </div>
          )}
        </div>
        <div className="stack" style={{ gap: 24 }}>
          <CloseMonth month={month} summary={summary} people={people} toCheck={items.filter((r) => r.type === "confirm_match").length}
            openReimbursements={items.filter((r) => r.type === "reimburse_employee").length} />
          <DoneRecently activity={activity} approvals={approvals} recs={recs} />
        </div>
      </div>
    </>
  );
}

/** One to-do: its title, its badge and one fact (the one the list is sorted by), and the action. The rest is in its details. */
function TodoRow({ item, sort, open: startOpen }: { item: TodoItem; sort: TodoSort; open?: boolean }) {
  const [open, setOpen] = useState(Boolean(startOpen));
  useEffect(() => { if (startOpen) setOpen(true); }, [startOpen]);
  const rec = item.rec;
  const decision = useDecision(rec ?? null);
  const done = decision.approval && decision.approval.decision !== "rejected";
  const urgent = item.severity === "critical";
  const amount = item.amount && whole({ ...item.amount, amount: item.amount.amount.replace("-", "") });
  const fact = sort === "amount" && amount ? <span>{amount}</span>
    : (sort === "due" || sort === "urgent") && item.dueBy ? <span className={urgent ? "bad" : undefined}>Decide by {shortDate(item.dueBy)}</span>
    : item.addedAt ? <span><Added at={item.addedAt} /></span> : null;
  const body = (
    <>
      <span className="row-title">{item.title}</span>
      <span className="row-sub"><StatusLabel level={done ? "approved" : item.level} />{fact}</span>
    </>
  );
  return (
    <div id={item.id} className={`todo-row-item${urgent ? " critical" : ""}`}>
      {rec ? <button type="button" className="row-main" onClick={() => setOpen(true)}>{body}</button> : <div className="row-main">{body}</div>}
      {decision.error && <span className="small bad" role="alert" title={decision.error}>Not done</span>}
      {decision.approval ? <Result approval={decision.approval} compact />
        : item.primary.kind === "approve" && rec ? <SimButton label={item.primary.label} busy={decision.busy} what={rec.proposed_action?.preview} onClick={() => decision.decide("approve")} />
        : item.primary.to ? <Link to={item.primary.to} className="button">{item.primary.label}</Link> : null}
      {open && rec && <RecModal rec={rec} decision={decision} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** A coming cash gap: when, how bad, and the prepared ways to close it, cheapest first. */
function GapCard({ item, onNotNow, target }: { item: TodoItem; onNotNow: () => void; target: string }) {
  const gap = item.gap!;
  return (
    <div id="gap" className="card stack gap-card" style={{ gap: 12 }}>
      <StatusLabel level="approval_required" />
      <div className="stack" style={{ gap: 2 }}>
        <span className="heading">{item.title}</span>
        <span className="small t2"><span className="bad">Lowest {whole(gap.lowest.amount)} on {shortDate(gap.lowest.date)}</span> · short by up to {whole(gap.short)}</span>
      </div>
      {gap.options.length > 0 && (
        <div className="stack" style={{ gap: 0 }}>
          <span className="caption t3">Options, cheapest first</span>
          {gap.options.map((r, i) => <GapOption key={r.id} rec={r} first={i === 0} open={target === r.id} />)}
        </div>
      )}
      <div className="hstack">
        <Link to="/#cash" className="button quiet">See it on the cash chart</Link>
        <button type="button" className="quiet" onClick={onNotNow}>Not now</button>
      </div>
    </div>
  );
}

function GapOption({ rec, first, open: startOpen }: { rec: Recommendation; first: boolean; open?: boolean }) {
  const decision = useDecision(rec);
  const [open, setOpen] = useState(Boolean(startOpen));
  const cost = costLabel(rec);
  return (
    <div className="option" id={rec.id}>
      <div className="stack grow" style={{ gap: 2 }}>
        <button type="button" className="row-title" onClick={() => setOpen(true)}>{rec.title}</button>
        {decision.approval && <span className="small t2">{decision.approval.execution.result}</span>}
        {decision.error && <span className="small bad" role="alert">Not done: {decision.error}</span>}
      </div>
      {cost && !decision.approval && <span className={`small ${cost === "Free" ? "good" : "t2"}`}>{cost}</span>}
      {decision.approval ? <Result approval={decision.approval} compact /> : (
        <>
          {canApprove(rec) && <SimButton label={approveLabel(rec)} primary={first} busy={decision.busy} what={rec.proposed_action?.preview} onClick={() => decision.decide("approve")} />}
        </>
      )}
      {open && <RecModal rec={rec} decision={decision} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** Month close: when every cost has a type and an invoice, the month can go to the accountant. */
function CloseMonth({ month, summary, people, toCheck, openReimbursements }: { month: string; summary: LedgerSummary | null; people: PeopleCosts | null; toCheck: number; openReimbursements: number }) {
  const currency = useCompanyInfo()?.base_currency ?? "PLN";
  const [sent, setSent] = useState(false);
  if (!summary) return null;
  const f = monthFigures(summary, currency);
  if (!f.hasData) {
    return (
      <div className="card stack" style={{ gap: 12 }}>
        <h2>Close {monthOnly(month)}</h2>
        <span className="t2">Nothing from {monthOnly(month)} is in the books yet. Payments go into the books once their invoice is matched and checked.</span>
        <Link to={`/money/payments?month=${month}`} className="button" style={{ alignSelf: "flex-start" }}>See {monthOnly(month)}'s payments</Link>
      </div>
    );
  }
  const explained = 100 - percent(f.unexplained.amount, f.costs.amount);
  const missing = summary.kpis.documents_missing;
  const receipts = people ? people.items.reduce((n, p) => n + p.receipts_owed, 0) : openReimbursements;
  const ready = explained === 100 && missing === 0;
  return (
    <div className="card stack" style={{ gap: 12 }}>
      <h2>Close {monthOnly(month)}</h2>
      <span className="number">{explained}% done</span>
      <div className="progress"><span style={{ width: `${explained}%` }} /></div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="kv"><span className="t2">Matched invoices to check</span><span className={toCheck ? "warn" : "good"}>{toCheck}</span></div>
        <div className="kv"><span className="t2">Payments without an invoice</span><span className={missing ? "bad" : "good"}>{missing}</span></div>
        <div className="kv"><span className="t2">Receipts to pay back</span><span className={receipts ? "warn" : "good"}>{receipts}</span></div>
      </div>
      {sent ? <DoneChip />
        : <span style={{ alignSelf: "flex-start" }}><SimButton label="Send to accountant" primary={false} disabled={!ready} what="Records the month as sent to your accountant." onClick={() => setSent(true)} /></span>}
    </div>
  );
}

/** What was done lately, in two lists: what the owner approved, and what Ordo did on its own. Each opens its details. */
function DoneRecently({ activity, approvals, recs }: { activity: ActivityItem[]; approvals: Approval[]; recs: Recommendation[] }) {
  const { approved, alone } = doneRecently(activity, approvals, recs, 4);
  const [tab, setTab] = useState<"you" | "ordo">(approved.length || !alone.length ? "you" : "ordo");
  const [open, setOpen] = useState<Done | null>(null);
  const items = tab === "you" ? approved : alone;
  const tabs: ["you" | "ordo", string, number][] = [["you", "Approved by you", approved.length], ["ordo", "By Ordo", alone.length]];
  return (
    <div className="card stack" style={{ gap: 14 }}>
      <div className="hstack"><h2 className="grow">Done recently</h2><Link to="/activity" className="small">See all</Link></div>
      <div className="tabs split" role="tablist" aria-label="Done by">
        {tabs.map(([key, label, n]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "on" : undefined} onClick={() => setTab(key)}>
            {label}<span className="tab-count">{n}</span>
          </button>
        ))}
      </div>
      {items.length === 0 ? (
        <div className="done-empty small t2">{tab === "you" ? "Nothing approved yet. What you approve in To-do shows up here." : "Ordo has not done anything on its own yet."}</div>
      ) : (
        <ol className="timeline">{items.map((d) => <LogLine key={d.at + d.text} d={d} onOpen={setOpen} />)}</ol>
      )}
      {open && <DoneModal done={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
