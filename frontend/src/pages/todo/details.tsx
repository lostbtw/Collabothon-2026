// The details popup of a recommendation, and the decision on it, shared by To-do and the activity log.
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Approval, Recommendation } from "../../api/types.gen";
import { Icon } from "../../components/Icon";
import { Modal, ModalSection } from "../../components/Modal";
import { Sources } from "../../components/Sources";
import { DoneChip, SimButton, StatusLabel } from "../../components/ui";
import { ago, useNow } from "../../lib/clock";
import { dateTime, shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { requestRefresh } from "../../lib/refresh";
import { firstSentence, whole } from "../../lib/words";
import { buildDecision, canApprove, editableAmount, parseAmount, resultHeadline } from "../inbox/model";
import { approveLabel, costLabel } from "./model";

export const AGENT: Record<string, string> = { ingestion: "Documents", liquidity: "Cash", tax: "Tax", fx: "FX Shield", chat: "Ask Ordo" };

export function Added({ at }: { at: string }) {
  const now = useNow(60_000);
  return <>Added {now === null ? dateTime(at) : ago(at, now)}</>;
}

export function RecModal({ rec, decision, onClose, approval, footer: given, extra }: {
  rec: Recommendation; decision?: Decision; onClose: () => void; approval?: Approval | null; footer?: ReactNode; extra?: ReactNode;
}) {
  const edit = editableAmount(rec);
  const [typed, setTyped] = useState(edit ? formatMoney(edit.value).replace(` ${edit.value.currency}`, "") : "");
  const amount = edit ? parseAmount(typed) : null;
  const [full, setFull] = useState(false);
  const result = approval ?? decision?.approval ?? null;
  const decidable = Boolean(decision) && !result && canApprove(rec);
  const level = result && result.decision !== "rejected" ? "approved" : rec.control_level;
  const link = rec.evidence.find((e) => e.url?.startsWith("/"))?.url;
  const footer = decidable ? (
    <>
      {edit && (
        <label className="hstack small t2" style={{ gap: 8 }}>{edit.label}
          <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} style={{ width: 120 }} aria-label={edit.label} />{edit.value.currency}
        </label>
      )}
      <span className="grow" />
      <button type="button" disabled={decision!.busy} onClick={() => decision!.decide("reject")}>No, thanks</button>
      <SimButton label={approveLabel(rec)} busy={decision!.busy} disabled={Boolean(edit) && amount === null} what={rec.proposed_action?.preview} onClick={() => decision!.decide("approve", amount)} />
    </>
  ) : !result && rec.control_level === "recommendation" && link ? (
    <><span className="grow" /><button type="button" onClick={onClose}>Close</button><Link to={link} className="button primary" onClick={onClose}>Check</Link></>
  ) : null;
  return (
    <Modal title={rec.title} onClose={onClose} footer={given ?? footer}
      head={<div className="hstack small t3" style={{ gap: 8 }}><StatusLabel level={level} /><span>{AGENT[rec.agent]}</span><span>·</span><span><Added at={rec.created_at} /></span></div>}>
      <p className="t2">{full ? rec.summary : firstSentence(rec.summary)}</p>
      <RecFigures rec={rec} full={full} />
      {result && <Result approval={result} />}
      {extra}
      {decision?.error && <span className="small bad" role="alert">Not done: {decision.error}</span>}
      {edit && amount === null && decidable && <span className="small bad">Enter an amount such as 25,000.</span>}
      <button type="button" className="linklike more-toggle" aria-expanded={full} onClick={() => setFull(!full)}>
        {full ? "Hide full description" : "Show full description"}<span className={`chev-sm${full ? " up" : ""}`}><Icon name="chevron" size={14} /></span>
      </button>
      {full && (
        <div className="stack full-desc" style={{ gap: 20 }}>
          {rec.explanation.why.length > 0 && (
            <ModalSection title="Why">
              <ul className="reasons">{rec.explanation.why.map((w, i) => <li key={w} className="reason"><span className="reason-n">{i + 1}</span><span className="small">{w}</span></li>)}</ul>
            </ModalSection>
          )}
          {(rec.explanation.calculation ?? []).length > 0 && (
            <ModalSection title="How Ordo worked it out">
              <div className="calc">{rec.explanation.calculation!.map((c) => <div key={c.label} className="kv"><span className="t2">{c.label}</span><span>{c.value}</span></div>)}</div>
            </ModalSection>
          )}
          {(rec.explanation.alternatives ?? []).length > 0 && (
            <ModalSection title="Other ways">
              {rec.explanation.alternatives!.map((a) => (
                <div key={a.label} className="alt">
                  <div className="hstack"><span className="medium small grow">{a.label}</span>{a.cost && <span className="small t2">{isFree(a.cost.amount) ? "Free" : `About ${whole(a.cost)}`}</span>}</div>
                  {(a.pros || a.cons) && <span className="small t2">{[a.pros && `+ ${a.pros}`, a.cons && `− ${a.cons}`].filter(Boolean).join("  ")}</span>}
                </div>
              ))}
            </ModalSection>
          )}
          {(rec.explanation.assumptions ?? []).length > 0 && (
            <ModalSection title="Ordo assumed">
              <ul className="plain-list small t2">{rec.explanation.assumptions!.map((a) => <li key={a}>{a}</li>)}</ul>
            </ModalSection>
          )}
          {rec.evidence.length > 0 && <ModalSection title="Based on"><Sources links={rec.evidence} /></ModalSection>}
          {rec.proposed_action?.preview && !result && (
            <ModalSection title="If you say yes"><span className="small">{rec.proposed_action.preview.replace(/^SIMULATED:\s*/, "")}</span></ModalSection>
          )}
        </div>
      )}
    </Modal>
  );
}

const isFree = (amount: string) => /^-?0+(\.0+)?$/.test(amount);

function RecFigures({ rec, full }: { rec: Recommendation; full: boolean }) {
  const i = rec.impact;
  const facts: [string, ReactNode, string?][] = [];
  if (i?.cash_effect && !isFree(i.cash_effect.amount)) facts.push(["Amount", whole({ ...i.cash_effect, amount: i.cash_effect.amount.replace("-", "") })]);
  const cost = costLabel(rec);
  if (cost) facts.push(["Costs you", cost, cost === "Free" ? "good" : undefined]);
  if (full && i?.min_balance_before && i.min_balance_after) facts.push(["Lowest balance", <>{whole(i.min_balance_before)} → {whole(i.min_balance_after)}</>]);
  if (rec.valid_until) facts.push(["Decide by", shortDate(rec.valid_until), rec.severity === "critical" ? "bad" : undefined]);
  if (full) facts.push(["Ordo is sure", `${Math.round(rec.explanation.confidence * 100)}%`]);
  if (facts.length === 0) return null;
  return (
    <div className="facts">
      {facts.map(([label, value, tone]) => <div key={label} className="stack" style={{ gap: 0 }}><span className="small t3">{label}</span><span className={tone}>{value}</span></div>)}
    </div>
  );
}

export function Result({ approval, compact }: { approval: Approval; compact?: boolean }) {
  if (approval.decision === "rejected") return <span className="small t2">{resultHeadline(approval)}</span>;
  return (
    <div className={compact ? "hstack" : "box good"}>
      <DoneChip reference={approval.execution.reference} result={approval.execution.result} />
      {!compact && <span className="small">{approval.execution.result}</span>}
    </div>
  );
}

export type Decision = { busy: boolean; approval: Approval | null; error: string | null; decide: (kind: "approve" | "reject", amount?: string | null) => void };

export function useDecision(rec: Recommendation | null): Decision {
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function decide(kind: "approve" | "reject", amount?: string | null) {
    if (!rec) return;
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

