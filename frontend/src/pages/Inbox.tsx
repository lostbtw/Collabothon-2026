import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Approval, Recommendation } from "../api/types.gen";
import { ControlBadges } from "../components/ControlBadges";
import { Evidence, More, MoreGroup } from "../components/More";
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

// Design rule for this screen: the card shows the decision and the key figures only.
// Everything that explains it (why, evidence, numbers, other options) is one click away, closed by default.

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "approval", label: "Needs approval" },
  { key: "recommendation", label: "Recommendations" },
  { key: "decided", label: "Decided" },
];

type OnDecide = (rec: Recommendation, kind: "approve" | "reject", editedAmount: string | null) => Promise<void>;

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

  const decide: OnDecide = async (rec, kind, editedAmount) => {
    const approval = await api.decide(rec.id, buildDecision(rec, kind, editedAmount));
    setJustDecided((d) => ({ ...d, [rec.id]: { rec, approval } }));
    // Stay on the card so the owner sees the result; it now lives under "Decided".
    setFilter("decided");
    navigate(`/inbox/${rec.id}`, { replace: true });
    setReload((n) => n + 1);
    requestRefresh();
  };

  return (
    <PageState state={state} keepWhileLoading>
      {([inbox, all, approvals]) => (
        <InboxView lists={buildLists(inbox, all.items, approvals.items, justDecided)} filter={filter} onFilter={setFilter} selectedId={id} onDecide={decide} />
      )}
    </PageState>
  );
}

export function InboxView({ lists, filter, onFilter, selectedId, onDecide }: { lists: InboxLists; filter: Filter; onFilter: (f: Filter) => void; selectedId?: string; onDecide: OnDecide }) {
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
              </Link>
            );
          })}
        </nav>
        {selected ? <Detail key={selected.id} rec={selected} approval={lists.approvalFor(selected.id)} onDecide={onDecide} /> : <div className="card muted">Nothing selected.</div>}
      </div>
    </>
  );
}

function DecisionChip({ approval }: { approval: Approval }) {
  return approval.decision === "rejected" ? <span className="chip neutral">Rejected</span> : <span className="chip positive">Approved</span>;
}

/** Two lines of summary; the rest on request. */
function Summary({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 150;
  return (
    <div>
      <p className={`body15 tertiary${long && !open ? " clamp" : ""}`}>{text}</p>
      {long && <button type="button" className="linklike" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Show less" : "Show more"}</button>}
    </div>
  );
}

export function Detail({ rec, approval, onDecide }: { rec: Recommendation; approval?: Approval; onDecide: OnDecide }) {
  const x = rec.explanation;
  const facts = impactFacts(rec);
  const by = x.generated_by;
  return (
    <article className="card detail">
      <div className="hstack">
        <ControlBadges level={rec.control_level} execution={rec.execution_mode} />
        {approval && <DecisionChip approval={approval} />}
      </div>
      <div className="stack" style={{ gap: 8 }}>
        <h1>{rec.title}</h1>
        <Summary text={rec.summary} />
      </div>
      {facts.length > 0 && (
        <div className="impact">
          {facts.map((f) => (
            <div key={f.label}><div className="caption muted">{f.label}</div><div className={`heading${f.tone ? ` ${f.tone}` : ""}`}>{f.value}</div></div>
          ))}
        </div>
      )}

      {approval ? <Result approval={approval} /> : <Decision rec={rec} onDecide={onDecide} />}

      <MoreGroup>
        <More title="Why" count={x.why.length}>
          <ol className="reasons">
            {x.why.map((w, i) => (<li key={w} className="reason"><span className="reason-n">{i + 1}</span><span>{w}</span></li>))}
          </ol>
        </More>
        <More title="Evidence" count={rec.evidence.length}><Evidence links={rec.evidence} /></More>
        {x.calculation && x.calculation.length > 0 && (
          <More title="The numbers" count={x.calculation.length}>
            {x.calculation.map((c) => (
              <div key={c.label} className="calc-row">
                <div className="grow"><div>{c.label}</div>{c.formula && <div className="caption muted">{c.formula}</div>}</div>
                <div className="medium right">{c.value}</div>
              </div>
            ))}
          </More>
        )}
        {x.alternatives && x.alternatives.length > 0 && (
          <More title="Other options" count={x.alternatives.length}>
            {x.alternatives.map((a) => (
              <div key={a.label} className="calc-row">
                <div className="grow"><div>{a.label}</div><div className="caption muted">{[a.pros, a.cons].filter(Boolean).join(". ")}</div></div>
                <div className="tertiary right">{a.cost ? formatMoney(a.cost, { decimals: false }) : "cost unknown"}</div>
              </div>
            ))}
          </More>
        )}
        <More title="About this card">
          <p className="small tertiary">{AGENT_LABEL[rec.agent]} · {dateTime(rec.created_at)} · {Math.round(x.confidence * 100)}% confident</p>
          {by && <p className="small tertiary">Numbers: {by.numbers === "finance-engine" ? "finance engine" : by.numbers}. Wording: {by.wording === "template" ? "fixed template" : "the model on your cluster"}.{by.trace_id ? ` Trace ${by.trace_id}.` : ""}</p>}
          {(x.assumptions ?? []).map((a) => <p key={a} className="small tertiary">Assumes: {a}</p>)}
        </More>
      </MoreGroup>
    </article>
  );
}

function Decision({ rec, onDecide }: { rec: Recommendation; onDecide: OnDecide }) {
  const edit = editableAmount(rec);
  const original = edit ? formatMoney(edit.value).replace(` ${edit.value.currency}`, "") : "";
  const [amount, setAmount] = useState(original);
  const [step, setStep] = useState<"idle" | "approve" | "reject">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canApprove(rec)) {
    return <p className="small muted">{rec.control_level !== "approval_required" ? "Advice only. Nothing to approve." : "This action cannot run in this build. Only simulated actions are allowed."}</p>;
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
    <div className="stack">
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
        </div>
      )}
      {invalid && step === "idle" && <p className="danger small" role="alert">Enter an amount such as 25000 or 25,000.00.</p>}
      {step === "approve" && (
        <div className="confirm" role="alertdialog" aria-label="Confirm approval">
          <p className="medium">Approve? This is SIMULATED.</p>
          <p className="tertiary">{rec.proposed_action?.preview ?? "It runs against the Sandbox Bank only. No real bank is contacted."}</p>
          {changed && edit && parsed && <p>New {edit.label.toLowerCase()}: {formatMoney({ amount: parsed, currency: edit.value.currency })} (was {formatMoney(edit.value)}).</p>}
          <div className="hstack">
            <button type="button" className="primary" disabled={busy} onClick={() => run("approve")}>{busy ? "Sending…" : "Yes, approve (SIMULATED)"}</button>
            <button type="button" className="outline" disabled={busy} onClick={() => setStep("idle")}>Back</button>
          </div>
        </div>
      )}
      {step === "reject" && (
        <div className="confirm" role="alertdialog" aria-label="Confirm rejection">
          <p className="medium">Reject? Nothing will be sent.</p>
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
  const changes = describeChanges(approval).map(([k, v]) => `${k.toLowerCase()} changed to ${v}`);
  return (
    <div className={`result-box ${rejected ? "neutral" : "positive"}`} role="status">
      <p className={`body15 medium${rejected ? "" : " positive"}`}>{resultHeadline(approval)}</p>
      {!rejected && approval.execution.result && <p>{approval.execution.result}</p>}
      <p className="small tertiary">{[`${rejected ? "Rejected" : "Approved"} by ${approval.decided_by.name}`, dateTime(approval.decided_at), ...changes].join(" · ")}</p>
      {!rejected && approval.execution.effects && approval.execution.effects.length > 0 && <Evidence links={approval.execution.effects} />}
    </div>
  );
}
