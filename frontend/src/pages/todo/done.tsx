// What was done, by the owner or by Ordo: one log line, its details popup, and Undo. Shared by To-do and Activity.
import { useEffect, useState } from "react";
import { api, type ActivityItem, type DocumentDetail } from "../../api/client";
import type { Match, OrdoDocument } from "../../api/types.gen";
import { Icon } from "../../components/Icon";
import { Modal, ModalSection } from "../../components/Modal";
import { Sources } from "../../components/Sources";
import { Chevron, StatusLabel } from "../../components/ui";
import { dateTime, shortDate } from "../../lib/dates";
import { requestRefresh } from "../../lib/refresh";
import { AGENT, Added, RecModal, Result } from "./details";
import { headline, undoKind, type Done } from "./model";

export const CHANNEL_LABEL: Record<OrdoDocument["channel"], string> = { ksef: "E-invoice (XML)", email: "PDF by e-mail", photo: "Photo", accounting_api: "Accounting tool", upload: "Upload" };

export type ActivityDetail = { kind: "document"; data: DocumentDetail } | { kind: "match"; match: Match } | null;

/** What stands behind one of Ordo's steps: the merged copies of a document, or the reasons of a match. */
export async function loadDetail(item: ActivityItem): Promise<ActivityDetail> {
  if (item.subject?.type === "document") return { kind: "document", data: await api.document(item.subject.id) };
  if (item.subject?.type === "match") {
    const match = (await api.matches()).items.find((m) => m.id === item.subject!.id);
    return match ? { kind: "match", match } : null;
  }
  return null;
}

export const titleOf = (d: Done): string => (d.level === "approved" ? d.text : headline(d.text));
const clock = (iso: string) => dateTime(iso).split(", ")[1] ?? "";

/** One line of the log. `full` (the Activity page) adds the clock time and the status label. */
export function LogLine({ d, onOpen, full }: { d: Done; onOpen: (d: Done) => void; full?: boolean }) {
  const who = d.level === "approved" ? (d.saidNo ? "no" : "you") : "ordo";
  return (
    <li>
      <button type="button" className={`tl-item${full ? " full" : ""}`} onClick={() => onOpen(d)}>
        {full && <span className="tl-time">{clock(d.at)}</span>}
        <span className={`tl-dot ${who}`} aria-hidden="true">{who === "you" ? <Icon name="check" size={14} /> : who === "no" ? <Icon name="close" size={12} /> : "O"}</span>
        <span className="tl-body">
          <span className="tl-title">{titleOf(d)}</span>
          <span className="tl-sub">
            {!full && <span>{d.level === "approved" ? shortDate(d.at) : <Added at={d.at} />}</span>}
            {d.level === "approved" ? <span>You</span> : <span>Ordo · {AGENT[d.activity?.agent ?? ""] ?? "Agent"}</span>}
            {d.reference && <span className="tl-ref">{d.reference}</span>}
            {full && undoKind(d) && <span>Can be undone</span>}
          </span>
        </span>
        {full && (d.saidNo ? <span className="status by-ordo">You said no</span> : <StatusLabel level={d.level} />)}
        <Chevron />
      </button>
    </li>
  );
}

type Undo = { kind: ReturnType<typeof undoKind>; busy: boolean; done: string | null; error: string | null; run: () => void };

/** Undo of an approved action (reversed in the test bank) or of a match Ordo made on its own (the match is rejected). */
function useUndo(d: Done): Undo {
  const kind = undoKind(d);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      if (kind === "match") {
        await api.decideMatch(d.activity!.subject!.id, { decision: "rejected", channel: "dashboard" });
        setDone("Undone. The invoice and the payment are no longer paired; the payment waits in Finances for its invoice.");
      } else if (kind === "approval") {
        const undone = await api.undoApproval(d.approval!.id);
        if (undone === null) return setError("Not undone: the backend cannot undo approved actions yet.");
        setDone(undone.execution.result ?? "Undone.");
      }
      requestRefresh();
    } catch (e) {
      setError(`Not undone: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }
  return { kind, busy, done, error, run: () => void run() };
}

function UndoFooter({ undo, onClose }: { undo: Undo; onClose: () => void }) {
  return (
    <>
      <span className="grow" />
      <button type="button" onClick={onClose}>Close</button>
      {!undo.done && (
        <button type="button" className="undo" disabled={!undo.kind || undo.busy} onClick={undo.run}>
          <Icon name="undo" size={16} />{undo.busy ? "Undoing…" : "Undo"}
        </button>
      )}
    </>
  );
}

function UndoResult({ undo }: { undo: Undo }) {
  if (undo.done) return <div className="box plain small"><span className="medium">Undone</span>{undo.done}</div>;
  if (undo.error) return <span className="small bad" role="alert">{undo.error}</span>;
  return null;
}

/** The details of a log line, with Undo where it is possible. */
export function DoneModal({ done, onClose }: { done: Done; onClose: () => void }) {
  const undo = useUndo(done);
  const [detail, setDetail] = useState<ActivityDetail | undefined>(done.activity ? undefined : null);
  useEffect(() => {
    if (done.activity) void loadDetail(done.activity).catch(() => null).then(setDetail);
  }, [done]);
  const footer = <UndoFooter undo={undo} onClose={onClose} />;
  if (done.rec) return <RecModal rec={done.rec} approval={done.approval} onClose={onClose} footer={footer} extra={<UndoResult undo={undo} />} />;
  return (
    <Modal title={titleOf(done)} onClose={onClose} footer={footer}
      head={<div className="hstack small t3" style={{ gap: 8 }}>{done.saidNo ? <span className="status by-ordo">You said no</span> : <StatusLabel level={done.level} />}<span>{dateTime(done.at)}</span></div>}>
      <UndoResult undo={undo} />
      {done.level === "approved" && done.approval && <Result approval={done.approval} />}
      {done.level === "analysed_autonomously" && <OrdoDetails done={done} detail={detail} />}
    </Modal>
  );
}

/** One of Ordo's own steps: what happened, what stands behind it, and where it came from. */
export function OrdoDetails({ done, detail }: { done: Done; detail: ActivityDetail | undefined }) {
  const a = done.activity;
  return (
    <>
      <ModalSection title="What happened"><p className="small log-line">{done.text}</p></ModalSection>
      {detail === undefined && <span className="skeleton line" style={{ width: "60%" }} />}
      {detail?.kind === "document" && detail.data.duplicates.length > 0 && (
        <ModalSection title={`${detail.data.duplicates.length + 1} copies → one record`}>
          <div className="hstack">{[detail.data.document, ...detail.data.duplicates].map((c) => <span key={c.id} className="chip neutral">{CHANNEL_LABEL[c.channel]}</span>)}</div>
        </ModalSection>
      )}
      {detail?.kind === "match" && (
        <ModalSection title="Why Ordo paired them">
          <ol className="reasons">{detail.match.reasons.map((r, i) => <li key={r.rule} className="reason"><span className="reason-n">{i + 1}</span><span className="small">{r.detail}</span></li>)}</ol>
        </ModalSection>
      )}
      {a && a.evidence.length > 0 && <ModalSection title="Based on"><Sources links={a.evidence} /></ModalSection>}
    </>
  );
}
