import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type DocumentDetail as DocumentData, type DocumentPatch } from "../api/client";
import type { OrdoDocument, Recommendation } from "../api/types.gen";
import { ControlBadges } from "../components/ControlBadges";
import { More, MoreGroup } from "../components/More";
import { OriginalModal, useOriginal } from "../components/OriginalFile";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { shortDate } from "../lib/dates";
import { requestRefresh } from "../lib/refresh";
import { useApi } from "../lib/useApi";
import { plainName } from "../lib/words";
import { buildPatch, fields, flagNotes, whoPaid, words, type FieldKey } from "./documents/model";

const STATUS_CHIP: Record<OrdoDocument["status"], string> = { extracted: "neutral", needs_review: "warning", approved: "positive", rejected: "neutral", duplicate: "neutral" };

export function DocumentDetail() {
  const { id = "" } = useParams();
  const { companyId } = useCompany();
  const [reload, setReload] = useState(0);
  const state = useApi(() => Promise.all([api.document(id), api.inbox(companyId).catch(() => null)]), [id, companyId, reload]);
  async function save(patch: DocumentPatch) {
    await api.patchDocument(id, patch);
    setReload((n) => n + 1);
    requestRefresh();
  }
  return (
    <PageState state={state} keepWhileLoading>
      {([data, inbox]) => <DocumentView data={data} card={inbox?.items.find((r) => r.subject?.id === data.document.id)} onSave={save} />}
    </PageState>
  );
}

export function DocumentView({ data, card, onSave }: { data: DocumentData; card?: Recommendation; onSave: (patch: DocumentPatch) => Promise<void> }) {
  const { document: d, matches, duplicates } = data;
  const match = matches[0];
  const paid = whoPaid(match);
  const notes = flagNotes(d, match);
  return (
    <>
      <div className="stack" style={{ gap: 8 }}>
        <Link to="/money/payments" className="small">← All payments</Link>
        <div className="hstack">
          <h1>{plainName(d.seller.name)}</h1>
          <span className={`chip ${STATUS_CHIP[d.status]}`}>{words(d.status)}</span>
        </div>
        <p className="tertiary">{[words(d.doc_type), d.number, d.issue_date && shortDate(d.issue_date)].filter(Boolean).join(" · ")}</p>
      </div>
      <div className="doc-cols">
        <Preview d={d} />
        <div className="stack" style={{ gap: 16 }}>
          {paid && (
            <div className="banner">
              <div className="grow">
                <div className="body15 medium">{paid.headline}</div>
                {paid.detail && <div className="tertiary">{paid.detail}</div>}
              </div>
              {card && <Link to={`/todo#${card.id}`} className="button primary">Decide</Link>}
            </div>
          )}
          {notes.map((n) => <div key={n} className="note">{n}</div>)}
          <Fields key={d.id + d.totals.gross.amount + d.issue_date + d.buyer.tax_id + d.seller.tax_id + d.totals.vat?.amount} d={d} onSave={onSave} />
          <MoreGroup>
            {match && (
              <More title="Why Ordo thinks so" count={match.reasons.length}>
                <ol className="reasons">{match.reasons.map((r, i) => <li key={r.rule} className="reason"><span className="reason-n">{i + 1}</span><span>{r.detail}</span></li>)}</ol>
                {match.consequences.note && <p className="small tertiary">{match.consequences.note}</p>}
              </More>
            )}
            {(d.lines?.length ?? 0) > 0 && (
              <More title="Items" count={d.lines!.length}>
                {d.lines!.map((l) => <div key={l.description} className="calc-row"><div className="grow">{l.description}</div><div className="tertiary right">{l.quantity} × {l.unit_price}</div></div>)}
              </More>
            )}
            {duplicates.length > 0 && (
              <More title="Copies merged into this one" count={duplicates.length}>
                {duplicates.map((c) => <div key={c.id} className="calc-row"><div className="grow">{words(c.channel)}</div><div className="tertiary right">{c.number}</div></div>)}
              </More>
            )}
            <More title="How it was read">
              <ControlBadges level="analysed_autonomously" />
              <p className="small tertiary">{words(d.extraction.method)} · {Math.round(d.extraction.confidence * 100)}% confident{d.extraction.trace_id ? ` · trace ${d.extraction.trace_id}` : ""}</p>
              {(d.extraction.warnings ?? []).map((w) => <p key={w} className="small tertiary">{w}</p>)}
            </More>
          </MoreGroup>
        </div>
      </div>
    </>
  );
}

function Preview({ d }: { d: OrdoDocument }) {
  const original = useOriginal(d);
  const [open, setOpen] = useState(false);
  const title = `Original ${words(d.doc_type)} from ${plainName(d.seller.name)}`;
  if (original?.kind === "image") {
    return (
      <div className="card doc-preview">
        <button type="button" className="original-button" onClick={() => setOpen(true)} title="Show it large"><img src={original.url} alt={title} /></button>
        {open && <OriginalModal original={original} title={title} onClose={() => setOpen(false)} />}
      </div>
    );
  }
  if (original) return <div className="card doc-preview"><iframe className="original-pdf" src={original.url} title={title} /><a className="small" href={original.url} target="_blank" rel="noreferrer">Open the PDF in a new tab</a></div>;
  return (
    <div className="card doc-preview">
      <div className="slip">
        <div className="medium">{plainName(d.seller.name)}</div>
        <div className="caption">{d.seller.tax_id ? `Tax no. ${d.seller.tax_id}` : ""}</div>
        <div className="caption">{d.number}</div>
        <hr />
        {(d.lines ?? []).map((l) => <div key={l.description} className="slip-row"><span>{l.description}</span><span>{l.unit_price}</span></div>)}
        <hr />
        <div className="slip-row"><span>VAT</span><span>{d.totals.vat?.amount ?? "—"}</span></div>
        <div className="slip-row medium"><span>TOTAL {d.totals.gross.currency}</span><span>{d.totals.gross.amount}</span></div>
        {d.payment?.card_last4 && <div className="caption">Card *{d.payment.card_last4}</div>}
      </div>
    </div>
  );
}

function Fields({ d, onSave }: { d: OrdoDocument; onSave: (patch: DocumentPatch) => Promise<void> }) {
  const rows = fields(d);
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState(() => Object.fromEntries(rows.map((f) => [f.key, f.input])) as Record<FieldKey, string>);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const { patch, error: problem } = buildPatch(d, edits);
    if (problem) return setError(problem);
    if (!patch) return setEditing(false);
    setBusy(true);
    setError(null);
    try {
      await onSave(patch);
      setEditing(false);
    } catch (e) {
      setError(`Not saved: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      {rows.map((f) => (
        <label key={f.key} className="field-row">
          <span className="tertiary">{f.label}</span>
          {editing
            ? <input type="text" value={edits[f.key]} onChange={(e) => setEdits({ ...edits, [f.key]: e.target.value })} />
            : <span className={f.low || f.missing ? "check" : undefined}>{f.value}{f.low ? " · please check" : ""}</span>}
        </label>
      ))}
      {error && <p className="danger small" role="alert">{error}</p>}
      <div className="hstack">
        {editing
          ? <><button type="button" className="primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button><button type="button" className="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</button></>
          : <button type="button" className="outline" onClick={() => setEditing(true)}>Correct a field</button>}
      </div>
    </div>
  );
}
