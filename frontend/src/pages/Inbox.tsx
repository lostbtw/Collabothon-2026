import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Approval, EvidenceLink, Recommendation } from "../api/types.gen";
import { ControlBadges } from "../components/ControlBadges";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { dateTime, shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { requestRefresh } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import {
  AGENT_LABEL, buildDecision, buildLists, canApprove, describeChanges, editableAmount, impactFacts, listFor, parseAmount, resultHeadline,
  type Decided, type Filter, type InboxLists,
} from "./inbox/model";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "approval", label: "Needs approval" },
  { key: "recommendation", label: "Recommendations" },
  { key: "decided", label: "Decided" },
];

export function Inbox() {
  const { companyId } = useCompany();
  const { id } = useParams();
  const navigate = useNavigate();
  const [reload, setReload] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [justDecided, setJustDecided] = useState<Record<string, Decided>>({});
  // The inbox itself must load; the decided list and past approvals are extras and may be missing.
  const state = useApi(
    () => Promise.all([api.inbox(companyId), api.recommendations(companyId).catch(() => ({ items: [] })), api.approvals(companyId).catch(() => ({ items: [] }))]),
    [companyId, reload],
  );

  async function decide(rec: Recommendation, kind: "approve" | "reject", editedAmount: string | null) {
    const approval = await api.decide(rec.id, buildDecision(rec, kind, editedAmount));
    setJustDecided((d) => ({ ...d, [rec.id]: { rec, approval } }));
    // Stay on the card so the owner sees the result; it now lives under "Decided".
    setFilter("decided");
    navigate(`/inbox/${rec.id}`, { replace: true });
    setReload((n) => n + 1);
    requestRefresh();
  }

  return (
    <PageState state={state} keepWhileLoading>
      {([inbox, all, approvals]) => (
        <InboxView lists={buildLists(inbox, all.items, approvals.items, justDecided)} filter={filter} onFilter={setFilter} selectedId={id} onDecide={decide} />
      )}
    </PageState>
  );
}

export function InboxView({ lists, filter, onFilter, selectedId, onDecide }: {
  lists: InboxLists;
  filter: Filter;
  onFilter: (f: Filter) => void;
  selectedId?: string;
  onDecide: (rec: Recommendation, kind: "approve" | "reject", editedAmount: string | null) => Promise<void>;
}) {
  const items = listFor(lists, filter);
  const selected = [...lists.open, ...lists.decided].find((r) => r.id === selectedId) ?? items[0];
  return (
    <>
      <div className="stack" style={{ gap: 16 }}>
        <h1>Inbox</h1>
        <div className="hstack" role="tablist" aria-label="Filter">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} className={filter === f.key ? "selected" : "outline"} onClick={() => onFilter(f.key)}>
              {f.label} <span className="muted">{lists.counts[f.key]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="inbox-cols">
        <nav className="card decision-list" aria-label="Cards">
          {items.length === 0 && <p className="muted" style={{ padding: 12 }}>{filter === "decided" ? "Nothing decided yet." : "Nothing is waiting for you."}</p>}
          {items.map((r) => {
            const approval = lists.approvalFor(r.id);
            return (
              <Link key={r.id} to={`/inbox/${r.id}`} className={`decision-item${selected?.id === r.id ? " active" : ""}`} aria-current={selected?.id === r.id ? "true" : undefined}>
                <div className="hstack" style={{ flexWrap: "nowrap" }}>
                  <ControlBadges level={r.control_level} execution={r.execution_mode} />
                  <span className="grow" />
                  {approval ? <DecisionChip approval={approval} /> : r.valid_until ? <span className="caption muted">by {shortDate(r.valid_until)}</span> : null}
                </div>
                <div className="body15 medium">{r.title}</div>
                <div className="caption muted">{AGENT_LABEL[r.agent]} · {dateTime(r.created_at)}</div>
              </Link>
            );
          })}
        </nav>
        {selected ? <Detail key={selected.id} rec={selected} approval={lists.approvalFor(selected.id)} onDecide={onDecide} /> : <div className="card muted">Select a card to see why Ordo suggests it.</div>}
      </div>
    </>
  );
}

function DecisionChip({ approval }: { approval: Approval }) {
  return approval.decision === "rejected" ? <span className="chip neutral">Rejected</span> : <span className="chip positive">Approved</span>;
}

function Evidence({ links }: { links: EvidenceLink[] }) {
  return (
    <div className="hstack">
      {links.map((e) => (e.url ? <Link key={e.kind + e.id} to={e.url} className="chip">{e.label}</Link> : <span key={e.kind + e.id} className="chip neutral">{e.label}</span>))}
    </div>
  );
}

export function Detail({ rec, approval, onDecide }: {
  rec: Recommendation;
  approval?: Approval;
  onDecide: (rec: Recommendation, kind: "approve" | "reject", editedAmount: string | null) => Promise<void>;
}) {
  const x = rec.explanation;
  const facts = impactFacts(rec);
  const by = x.generated_by;
  return (
    <article className="card detail">
      <div className="hstack">
        <ControlBadges level={rec.control_level} execution={rec.execution_mode} />
        {approval && <DecisionChip approval={approval} />}
        <span className="grow" />
        <span className="small muted">{AGENT_LABEL[rec.agent]} · {dateTime(rec.created_at)} · {Math.round(x.confidence * 100)}% confident</span>
      </div>
      <div className="stack" style={{ gap: 8 }}>
        <h1>{rec.title}</h1>
        <p className="body15 tertiary">{rec.summary}</p>
      </div>
      {facts.length > 0 && (
        <div className="impact">
          {facts.map((f) => (
            <div key={f.label}><div className="caption muted">{f.label}</div><div className={`heading${f.tone ? ` ${f.tone}` : ""}`}>{f.value}</div></div>
          ))}
        </div>
      )}

      <h2>Why</h2>
      <ol className="reasons">
        {x.why.map((w, i) => (<li key={w} className="reason"><span className="reason-n">{i + 1}</span><span>{w}</span></li>))}
      </ol>
      <div className="stack" style={{ gap: 8 }}>
        <div className="caption muted">Evidence</div>
        <Evidence links={rec.evidence} />
      </div>

      {x.calculation && x.calculation.length > 0 && (
        <>
          <hr className="divider" />
          <h2>The numbers</h2>
          <div className="stack">
            {x.calculation.map((c) => (
              <div key={c.label} className="calc-row">
                <div className="grow"><div>{c.label}</div>{c.formula && <div className="caption muted">{c.formula}</div>}</div>
                <div className="body15 medium right">{c.value}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {x.alternatives && x.alternatives.length > 0 && (
        <>
          <hr className="divider" />
          <h2>Other options</h2>
          <div className="stack">
            {x.alternatives.map((a) => (
              <div key={a.label} className="calc-row">
                <div className="grow"><div>{a.label}</div><div className="caption muted">{[a.pros, a.cons].filter(Boolean).join(". ")}</div></div>
                <div className="tertiary right">{a.cost ? formatMoney(a.cost, { decimals: false }) : "cost unknown"}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {approval ? <Result approval={approval} /> : <Decision rec={rec} onDecide={onDecide} />}

      <p className="caption muted">
        {(x.assumptions ?? []).map((a) => `${a}. `)}
        {by && <>Numbers: {by.numbers === "finance-engine" ? "finance engine" : by.numbers}. Wording: {by.wording === "template" ? "fixed template" : "the model on your cluster"}.{by.trace_id ? ` Trace ${by.trace_id}.` : ""}</>}
      </p>
    </article>
  );
}

function Decision({ rec, onDecide }: { rec: Recommendation; onDecide: (rec: Recommendation, kind: "approve" | "reject", editedAmount: string | null) => Promise<void> }) {
  const edit = editableAmount(rec);
  const original = edit ? formatMoney(edit.value).replace(` ${edit.value.currency}`, "") : "";
  const [amount, setAmount] = useState(original);
  const [step, setStep] = useState<"idle" | "approve" | "reject">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canApprove(rec)) {
    if (rec.control_level !== "approval_required") return <div className="result-box neutral"><p>Nothing to approve. This is advice; no action is prepared.</p><div className="hstack"><Link to="/chat" className="button outline">Ask Ordo about this</Link></div></div>;
    return <div className="result-box neutral"><p>This action cannot run in this build. Only simulated actions against the Sandbox Bank are allowed.</p></div>;
  }

  const parsed = edit ? parseAmount(amount) : null;
  const invalid = Boolean(edit) && parsed === null;
  const changed = Boolean(edit && parsed && parsed !== parseAmount(edit.value.amount));

  async function run(kind: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await onDecide(rec, kind, parsed);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="approve-box">
      <h2>What happens when you approve</h2>
      <p>{rec.proposed_action?.preview ?? "SIMULATED: the action runs against the Sandbox Bank. No real bank is contacted."}{edit && step === "idle" ? " You can change the amount first." : ""}</p>
      {step === "idle" && (
        <div className="hstack">
          {edit && (
            <label className="field">
              <span className="muted">{edit.label}</span>
              <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-invalid={invalid} />
              <span className="muted">{edit.value.currency}</span>
            </label>
          )}
          <button type="button" className="primary" disabled={invalid} onClick={() => setStep("approve")}>Approve (SIMULATED)</button>
          <button type="button" className="outline" onClick={() => setStep("reject")}>Reject</button>
          <Link to="/chat" className="button outline">Ask Ordo about this</Link>
        </div>
      )}
      {invalid && step === "idle" && <p className="danger small" role="alert">Enter an amount such as 25000 or 25,000.00.</p>}
      {step === "approve" && (
        <div className="confirm" role="alertdialog" aria-label="Confirm approval">
          <p className="medium">SIMULATED. Approve “{rec.title}”?</p>
          {changed && edit && parsed && <p>You changed the {edit.label.toLowerCase()} from {formatMoney(edit.value)} to {formatMoney({ amount: parsed, currency: edit.value.currency })}.</p>}
          <p className="tertiary">It is sent to the Sandbox Bank only. No real bank is contacted and no real money moves.</p>
          <div className="hstack">
            <button type="button" className="primary" disabled={busy} onClick={() => run("approve")}>{busy ? "Sending…" : "Yes, approve (SIMULATED)"}</button>
            <button type="button" className="outline" disabled={busy} onClick={() => setStep("idle")}>Back</button>
          </div>
        </div>
      )}
      {step === "reject" && (
        <div className="confirm" role="alertdialog" aria-label="Confirm rejection">
          <p className="medium">Reject “{rec.title}”?</p>
          <p className="tertiary">Nothing is sent anywhere. The card moves to Decided.</p>
          <div className="hstack">
            <button type="button" className="primary" disabled={busy} onClick={() => run("reject")}>{busy ? "Saving…" : "Yes, reject"}</button>
            <button type="button" className="outline" disabled={busy} onClick={() => setStep("idle")}>Back</button>
          </div>
        </div>
      )}
      {error && <p className="danger" role="alert">The decision was not saved: {error}</p>}
    </div>
  );
}

function Result({ approval }: { approval: Approval }) {
  const rejected = approval.decision === "rejected";
  const changes = describeChanges(approval);
  return (
    <div className={`result-box ${rejected ? "neutral" : "positive"}`} role="status">
      <p className={`body15 medium${rejected ? "" : " positive"}`}>{resultHeadline(approval)}</p>
      {!rejected && approval.execution.result && <p>{approval.execution.result}</p>}
      {changes.length > 0 && <p>You changed: {changes.map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ")}.</p>}
      <p className="small tertiary">{rejected ? "Rejected" : "Approved"} by {approval.decided_by.name} · {dateTime(approval.decided_at)}</p>
      {!rejected && approval.execution.effects && approval.execution.effects.length > 0 && <Evidence links={approval.execution.effects} />}
    </div>
  );
}
