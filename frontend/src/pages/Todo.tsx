// To-do: only what the owner decides. Every action runs only after a yes, and only in the sandbox.
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, type ActivityItem, type LedgerSummary, type PeopleCosts } from "../api/client";
import type { Approval, Forecast, Recommendation, Transaction } from "../api/types.gen";
import { Evidence } from "../components/More";
import { PageHead, Skeleton, StatusLabel } from "../components/ui";
import { lastFullMonth, monthFigures, monthOnly, monthRange, percent } from "../lib/costTypes";
import { useCompany, useCompanyInfo, useToday } from "../lib/company";
import { dateTime, shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { requestRefresh, useRefreshKey } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { whole } from "../lib/words";
import { buildDecision, canApprove, editableAmount, parseAmount, resultHeadline } from "./inbox/model";
import { approveLabel, buildTodo, costLabel, doneRecently, type TodoItem } from "./todo/model";

const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
const HIDDEN_KEY = "ordo.todo.notNow";
const hiddenNow = (): string[] => { try { return JSON.parse(window.sessionStorage.getItem(HIDDEN_KEY) ?? "[]") as string[]; } catch { return []; } };

export function Todo() {
  const { companyId } = useCompany();
  const today = useToday();
  const refresh = useRefreshKey();
  const month = lastFullMonth(today);
  const state = useApi(() => Promise.all([
    api.inbox(companyId), none(api.forecast(companyId)), none(api.recommendations(companyId)), none(api.approvals(companyId)), none(api.activity(companyId)),
  ]), [companyId, refresh]);
  const close = useApi(() => Promise.all([
    none(api.ledgerSummary(companyId, { groupBy: "category", ...monthRange(month) })), none(api.transactions(companyId)), none(api.peopleCosts(companyId, month)),
  ]), [companyId, month, refresh]);

  if (state.loading && !state.data) return <><PageHead title="To-do" sub="Only you can decide these. Nothing happens until you say yes." /><Skeleton rows={5} title /><Skeleton rows={3} /></>;
  if (state.error) return <><PageHead title="To-do" /><p className="bad" role="alert">Could not load To-do: {state.error}</p></>;
  const [inbox, forecast, recs, approvals, activity] = state.data!;
  const [summary, transactions, people] = close.data ?? [null, null, null];
  return (
    <TodoView items={inbox.items} forecast={forecast} recs={recs?.items ?? inbox.items} approvals={approvals?.items ?? []} activity={activity?.items ?? []}
      month={month} summary={summary} transactions={transactions?.items ?? []} people={people} />
  );
}

type ViewProps = {
  items: Recommendation[]; forecast: Forecast | null; recs: Recommendation[]; approvals: Approval[]; activity: ActivityItem[];
  month: string; summary: LedgerSummary | null; transactions: Transaction[]; people: PeopleCosts | null;
};

export function TodoView({ items, forecast, recs, approvals, activity, month, summary, transactions, people }: ViewProps) {
  const { hash } = useLocation();
  const [hidden, setHidden] = useState<string[]>(hiddenNow);
  const todo = buildTodo(items, forecast);
  const needsOk = todo.needsOk.filter((i) => !hidden.includes(i.id));
  const target = decodeURIComponent(hash.replace(/^#/, ""));
  useEffect(() => { if (target) document.getElementById(target)?.scrollIntoView?.({ block: "start" }); }, [target]);
  function notNow(id: string) {
    const next = [...hidden, id];
    setHidden(next);
    try { window.sessionStorage.setItem(HIDDEN_KEY, JSON.stringify(next)); } catch { /* the choice lasts until reload */ }
  }
  return (
    <>
      <PageHead title="To-do" sub="Only you can decide these. Nothing happens until you say yes." />
      <div className="todo-cols">
        <div className="stack" style={{ gap: 32 }}>
          <section className="section">
            <div className="section-head"><h2>Needs your OK</h2><span className="t3">{needsOk.length}</span></div>
            {needsOk.length === 0 && <div className="card t2">Nothing waits for your OK.{hidden.length ? " Some items are hidden until you reload the page." : ""}</div>}
            {needsOk.map((item) => (item.gap
              ? <GapCard key={item.id} item={item} forecast={forecast} onNotNow={() => notNow(item.id)} />
              : item.rec ? <ItemCard key={item.id} item={item} open={target === item.id} />
              : <LinkCard key={item.id} item={item} />))}
          </section>
          {todo.check.length > 0 && (
            <section className="section">
              <div className="section-head"><h2>Check these</h2><span className="t3">{todo.check.length}</span></div>
              <div className="card stack" style={{ gap: 0, paddingTop: 12, paddingBottom: 12 }}>
                {todo.check.map((item) => (
                  <div key={item.id} id={item.id} className="list-row">
                    <div className="stack grow" style={{ gap: 4 }}>
                      <StatusLabel level="recommendation" />
                      <span className="medium">{item.title}</span>
                      <span className="small t2">{item.summary}</span>
                    </div>
                    {item.primary.to ? <Link to={item.primary.to} className="button">{item.primary.label}</Link> : null}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
        <div className="stack" style={{ gap: 24 }}>
          <CloseMonth month={month} summary={summary} transactions={transactions} people={people} openReimbursements={items.filter((r) => r.type === "reimburse_employee").length} />
          <DoneRecently activity={activity} approvals={approvals} recs={recs} />
        </div>
      </div>
    </>
  );
}

/** Many cards of one kind, shown as one to-do that leads to where they are checked one by one. */
function LinkCard({ item }: { item: TodoItem }) {
  return (
    <div id={item.id} className="card hstack" style={{ flexWrap: "nowrap", gap: 24 }}>
      <div className="stack grow" style={{ gap: 4 }}>
        <StatusLabel level={item.level} />
        <span className="medium">{item.title}</span>
        <span className="small t2">{item.summary}</span>
      </div>
      {item.primary.to && <Link to={item.primary.to} className="button">{item.primary.label}</Link>}
    </div>
  );
}

/** One prepared action or piece of advice. Details (why, numbers, evidence) are one click away. */
function ItemCard({ item, open: startOpen }: { item: TodoItem; open?: boolean }) {
  const rec = item.rec!;
  const [open, setOpen] = useState(Boolean(startOpen));
  const decision = useDecision(rec);
  return (
    <div id={item.id} className="card stack" style={{ gap: 12 }}>
      <div className="hstack" style={{ alignItems: "flex-start", flexWrap: "nowrap", gap: 24 }}>
        <div className="stack grow" style={{ gap: 4 }}>
          <StatusLabel level={decision.approval && decision.approval.decision !== "rejected" ? "approved" : item.level} />
          <span className="medium">{item.title}</span>
          <span className={`small t2${open ? "" : " clamp2"}`}>{rec.summary}</span>
        </div>
        {!decision.approval && (item.primary.kind === "approve"
          ? <button type="button" className="primary" disabled={decision.busy} onClick={() => decision.decide("approve")}>{decision.busy ? "Working…" : item.primary.label}</button>
          : <button type="button" onClick={() => setOpen(!open)}>{open ? "Hide details" : "See details"}</button>)}
      </div>
      {decision.approval && <Result approval={decision.approval} />}
      {decision.error && <span className="small bad" role="alert">Not done: {decision.error}</span>}
      {open && !decision.approval && <Details rec={rec} decision={decision} />}
    </div>
  );
}

function Details({ rec, decision }: { rec: Recommendation; decision: Decision }) {
  const edit = editableAmount(rec);
  const [typed, setTyped] = useState(edit ? formatMoney(edit.value).replace(` ${edit.value.currency}`, "") : "");
  const amount = edit ? parseAmount(typed) : null;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <hr className="divider" />
      <ul className="reasons">{rec.explanation.why.map((w, i) => <li key={w} className="reason"><span className="reason-n">{i + 1}</span><span className="small">{w}</span></li>)}</ul>
      {(rec.explanation.calculation ?? []).length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          {rec.explanation.calculation!.map((c) => <div key={c.label} className="kv"><span className="t2">{c.label}</span><span>{c.value}</span></div>)}
        </div>
      )}
      <Evidence links={rec.evidence} />
      {rec.proposed_action?.preview && <span className="small t3">{rec.proposed_action.preview}</span>}
      {canApprove(rec) && (
        <div className="hstack">
          {edit && (
            <label className="hstack small t2" style={{ gap: 8 }}>{edit.label}
              <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} style={{ width: 120 }} aria-label={edit.label} />{edit.value.currency}
            </label>
          )}
          <button type="button" className="primary" disabled={decision.busy || (edit !== null && amount === null)} onClick={() => decision.decide("approve", amount)}>{approveLabel(rec)}</button>
          <button type="button" disabled={decision.busy} onClick={() => decision.decide("reject")}>No, thanks</button>
        </div>
      )}
      {edit && amount === null && <span className="small bad">Enter an amount such as 25,000.</span>}
    </div>
  );
}

/** A coming cash gap, with every prepared way to close it, cheapest first. */
function GapCard({ item, forecast, onNotNow }: { item: TodoItem; forecast: Forecast | null; onNotNow: () => void }) {
  const gap = item.gap!;
  const found = gap.options[0]?.created_at ?? forecast?.generated_at;
  return (
    <div id="gap" className="card stack" style={{ gap: 16 }}>
      <div className="hstack">
        <StatusLabel level="approval_required" />
        <span className="grow" />
        {found && <span className="small t3">Found {dateTime(found)}</span>}
      </div>
      <span className="heading">{item.title}</span>
      <span className="t2">{item.summary}</span>
      <div className="facts">
        <div className="stack" style={{ gap: 0 }}><span className="small t3">Lowest point</span><span className="bad">{whole(gap.lowest.amount)} on {shortDate(gap.lowest.date)}</span></div>
        {gap.days !== null && <div className="stack" style={{ gap: 0 }}><span className="small t3">Days below zero</span><span>{gap.days}</span></div>}
        <div className="stack" style={{ gap: 0 }}><span className="small t3">Short by up to</span><span>{whole(gap.short)}</span></div>
      </div>
      {gap.options.length > 0 && (
        <div className="stack" style={{ gap: 0 }}>
          <span className="small t2">Options, cheapest first</span>
          {gap.options.map((r, i) => <GapOption key={r.id} rec={r} first={i === 0} />)}
        </div>
      )}
      <div className="hstack">
        <Link to="/#cash" className="button quiet">See it on the cash chart</Link>
        <button type="button" className="quiet" onClick={onNotNow}>Not now</button>
      </div>
    </div>
  );
}

function GapOption({ rec, first }: { rec: Recommendation; first: boolean }) {
  const decision = useDecision(rec);
  const edit = editableAmount(rec);
  const [editing, setEditing] = useState(false);
  const [typed, setTyped] = useState(edit ? formatMoney(edit.value).replace(` ${edit.value.currency}`, "") : "");
  const amount = edit && editing ? parseAmount(typed) : null;
  const cost = costLabel(rec);
  return (
    <div className="option" id={rec.id}>
      <div className="stack grow" style={{ gap: 2 }}>
        <span className="medium">{rec.title}</span>
        <span className="small t2">{decision.approval ? decision.approval.execution.result : rec.summary.split(". ").slice(0, 1).join("") + (rec.summary.includes(". ") ? "." : "")}</span>
        {editing && edit && (
          <label className="hstack small t2" style={{ gap: 8, marginTop: 4 }}>{edit.label}
            <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} style={{ width: 120 }} aria-label={edit.label} />{edit.value.currency}
            {amount === null && <span className="bad">Enter an amount such as 25,000.</span>}
          </label>
        )}
        {decision.error && <span className="small bad" role="alert">Not done: {decision.error}</span>}
      </div>
      {cost && !decision.approval && <span className={`small ${cost === "Free" ? "good" : "t2"}`}>{cost}</span>}
      {decision.approval ? <Result approval={decision.approval} compact /> : (
        <>
          {edit && !editing && <button type="button" className="quiet" onClick={() => setEditing(true)}>Change {edit.label.toLowerCase()}</button>}
          {canApprove(rec) && <button type="button" className={first ? "primary" : undefined} disabled={decision.busy || (editing && amount === null)} onClick={() => decision.decide("approve", amount)}>{decision.busy ? "Working…" : approveLabel(rec)}</button>}
        </>
      )}
    </div>
  );
}

function Result({ approval, compact }: { approval: Approval; compact?: boolean }) {
  if (approval.decision === "rejected") return <span className="small t2">{resultHeadline(approval)}</span>;
  return (
    <div className={compact ? "hstack" : "box good"}>
      <span className="simulated pulse">SIMULATED · {approval.execution.reference ?? "recorded"}</span>
      {!compact && <span className="small">{approval.execution.result}</span>}
    </div>
  );
}

type Decision = { busy: boolean; approval: Approval | null; error: string | null; decide: (kind: "approve" | "reject", amount?: string | null) => void };

function useDecision(rec: Recommendation): Decision {
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function decide(kind: "approve" | "reject", amount?: string | null) {
    setBusy(true);
    setError(null);
    try {
      setApproval(await api.decide(rec.id, buildDecision(rec, kind, amount)));
      requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, approval, error, decide: (kind, amount) => void decide(kind, amount) };
}

/** Month close: when every cost has a type and an invoice, the month can go to the accountant. */
function CloseMonth({ month, summary, transactions, people, openReimbursements }: { month: string; summary: LedgerSummary | null; transactions: Transaction[]; people: PeopleCosts | null; openReimbursements: number }) {
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
  const inMonth = transactions.filter((t) => t.booking_date.startsWith(month));
  const matched = inMonth.filter((t) => t.match_status === "matched" || t.match_status === "no_document_needed").length;
  const missing = summary.kpis.documents_missing;
  const receipts = people ? people.items.reduce((n, p) => n + p.receipts_owed, 0) : openReimbursements;
  const ready = explained === 100 && missing === 0;
  return (
    <div className="card stack" style={{ gap: 12 }}>
      <h2>Close {monthOnly(month)}</h2>
      <span className="number">{explained}% done</span>
      <div className="progress"><span style={{ width: `${explained}%` }} /></div>
      <span className="small t2">When every cost has an invoice and a type, send {monthOnly(month)} to your accountant in one click.</span>
      <div className="stack" style={{ gap: 6 }}>
        <div className="kv"><span className="t2">Bank payments matched</span><span className="good">{matched}</span></div>
        <div className="kv"><span className="t2">Payments without an invoice</span><span className={missing ? "bad" : "good"}>{missing}</span></div>
        <div className="kv"><span className="t2">Receipts to pay back</span><span className={receipts ? "warn" : "good"}>{receipts}</span></div>
      </div>
      {sent ? <span className="simulated pulse">SIMULATED · nothing left the app</span>
        : <button type="button" disabled={!ready} onClick={() => setSent(true)} style={{ alignSelf: "flex-start" }}>Send to accountant (simulated)</button>}
      {!ready && <span className="caption t3">Available when {monthOnly(month)} is 100% done</span>}
    </div>
  );
}

function DoneRecently({ activity, approvals, recs }: { activity: ActivityItem[]; approvals: Approval[]; recs: Recommendation[] }) {
  const done = doneRecently(activity, approvals, recs);
  return (
    <div className="card stack" style={{ gap: 0 }}>
      <h2 style={{ marginBottom: 8 }}>Done recently</h2>
      {done.length === 0 && <span className="small t2">Nothing yet.</span>}
      {done.map((d) => (
        <div key={d.at + d.text} className="list-row" style={{ alignItems: "flex-start" }}>
          <div className="stack" style={{ gap: 4 }}>
            <StatusLabel level={d.level} />
            <span className="small">{d.text}</span>
            {d.reference && <span className="simulated">SIMULATED · {d.reference}</span>}
          </div>
        </div>
      ))}
      <Link to="/activity" className="small" style={{ marginTop: 12 }}>See everything Ordo did</Link>
    </div>
  );
}
