// The panel next to All payments: one payment, the paper behind it, and what the owner can do about it.
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { api, rawContentUrl } from "../../api/client";
import type { Approval, Category, OrdoDocument, Recommendation } from "../../api/types.gen";
import { Icon } from "../../components/Icon";
import { CloseButton, DoneChip, SimButton, StatusLabel } from "../../components/ui";
import { useCompany } from "../../lib/company";
import { longDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { requestRefresh, useRefreshKey } from "../../lib/refresh";
import { useApi } from "../../lib/useApi";
import { CATEGORY_LABEL, categoryLabel, firstName, plainName } from "../../lib/words";
import { LOW_CONFIDENCE, flagNotes, whoPaid } from "../documents/model";
import { buildDecision } from "../inbox/model";
import { approveLabel } from "../todo/model";
import { typeOf, type Payment } from "./payments";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const none = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
/** How often and how long the panel waits for Ordo to read an added file. */
const POLL_MS = 1500;
const POLL_TRIES = 40;

type Upload = { state: "sending" | "reading" | "failed"; error?: string };

export function PaymentPanel({ payment: p, onClose, onChanged }: { payment: Payment; onClose: () => void; onChanged: () => void }) {
  const { companyId } = useCompany();
  const refresh = useRefreshKey();
  const extra = useApi(() => Promise.all([none(api.inbox(companyId)), none(api.sources(companyId))]), [companyId, refresh]);
  const [inbox, sources] = extra.data ?? [null, null];
  const card = inbox?.items.find((r) => r.subject && (r.subject.id === p.document?.id || r.subject.id === p.id)) ?? null;
  const mailbox = sources?.items.find((s) => s.connector === "imap_mailbox")?.config_public?.mailbox as string | undefined;
  const [upload, setUpload] = useState<Upload | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Set on every mount: React's development mode mounts twice and would otherwise leave it false.
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function sendFile(file: File) {
    setUpload({ state: "sending" });
    try {
      const raw = await api.upload(file, { companyId, submittedBy: "owner", transactionId: p.transaction?.id });
      setUpload({ state: "reading" });
      // Ordo reads the file in the background; wait for the document that comes from it.
      for (let i = 0; i < POLL_TRIES && alive.current; i++) {
        await sleep(POLL_MS);
        const docs = await api.documents(companyId);
        if (docs.items.some((d) => d.raw_item_ids.includes(raw.id))) {
          if (!alive.current) return;
          setUpload(null);
          onChanged();
          requestRefresh();
          return;
        }
      }
      if (alive.current) setUpload({ state: "failed", error: "The file is saved, but Ordo has not read it yet. It shows up here once it has." });
    } catch (e) {
      if (alive.current) setUpload({ state: "failed", error: `Not added: ${e instanceof Error ? e.message : String(e)}` });
    }
  }

  const sub = [p.date && longDate(p.date), cardText(p)].filter(Boolean).join(" · ");
  return (
    <aside className="card drawer" aria-label={`Payment ${p.name}`}>
      <div className="hstack" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
        <div className="stack grow" style={{ gap: 2 }}>
          <span className="heading">{p.name}</span>
          {sub && <span className="small t2">{sub}</span>}
        </div>
        <CloseButton onClick={onClose} />
      </div>
      <div className="stack" style={{ gap: 0 }}>
        <span className={`number${p.amount.amount.startsWith("-") ? "" : " good"}`}>{p.amount.amount.startsWith("-") ? "" : "+"}{formatMoney(p.amount)}</span>
        {p.original && <span className="small t3">{formatMoney(p.original)} paid</span>}
      </div>
      {upload ? <UploadState upload={upload} onRetry={() => setUpload(null)} />
        : p.doc === "to_check" && p.document ? <ReadResult p={p} d={p.document} onChanged={onChanged} />
        : card && card.control_level === "approval_required" ? <Decide p={p} card={card} />
        : p.doc === "missing" ? <Missing p={p} mailbox={mailbox} onFile={sendFile} />
        : p.doc === "not_needed" ? <div className="box plain"><span className="small">{notNeededReason(p)}</span></div>
        : null}
      {!upload && (p.doc === "on_file" || p.doc === "receipt") && <OnFile p={p} onFile={sendFile} />}
      <hr className="divider" />
      <Why p={p} onChanged={onChanged} />
    </aside>
  );
}

function cardText(p: Payment): string | null {
  if (p.transaction?.card_last4) return p.account?.kind === "owner_private" ? `owner's card ending ${p.transaction.card_last4}` : `company card ending ${p.transaction.card_last4}`;
  if (p.account) return p.account.name.charAt(0).toLowerCase() + p.account.name.slice(1);
  const last4 = p.document?.payment?.card_last4;
  if (p.match?.payer?.name) return `${firstName(p.match.payer.name)}'s card${last4 ? ` ending ${last4}` : ""}`;
  return null;
}

function notNeededReason(p: Payment): string {
  if (p.category === "taxes") return "No invoice needed: a tax payment has none.";
  if (p.category === "salaries" || p.category === "social_security") return "No invoice needed: it is paid from payroll.";
  return "No invoice needed for this payment.";
}

function UploadState({ upload, onRetry }: { upload: Upload; onRetry: () => void }) {
  if (upload.state === "failed") return <div className="box warn"><span className="small">{upload.error}</span><button type="button" onClick={onRetry} style={{ alignSelf: "flex-start" }}>OK</button></div>;
  return (
    <div className="box good">
      <StatusLabel level="analysed_autonomously" />
      <span>{upload.state === "sending" ? "Sending the file…" : "Ordo is reading it. This takes a few seconds."}</span>
      <div className="typing" role="status" aria-label="Reading"><span /><span /><span /></div>
    </div>
  );
}

/** A private payment with a prepared action: the owner approves it here, simulated. */
function Decide({ p, card }: { p: Payment; card: Recommendation }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const paid = whoPaid(p.match ?? undefined);
  async function approve() {
    setBusy(true);
    setError(null);
    try {
      setDone(await api.decide(card.id, buildDecision(card, "approve")));
      requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  if (done) {
    return (
      <div className="box good">
        <StatusLabel level="approved" />
        <DoneChip reference={done.execution.reference} result={done.execution.result} />
        <span className="small">{done.execution.result}</span>
      </div>
    );
  }
  return (
    <div className="box warn">
      <StatusLabel level="approval_required" />
      <span>{paid ? [paid.headline, paid.detail].filter(Boolean).join(". ") : card.title}</span>
      {error && <span className="small bad" role="alert">Not done: {error}</span>}
      <span style={{ alignSelf: "flex-start" }}>
        <SimButton busy={busy} what={card.proposed_action?.preview} onClick={approve}
          label={card.type === "reimburse_employee" && p.match?.payer?.name ? `Pay ${firstName(p.match.payer.name)} back` : approveLabel(card)} />
      </span>
    </div>
  );
}

function Missing({ p, mailbox, onFile }: { p: Payment; mailbox?: string; onFile: (f: File) => void }) {
  const income = !p.amount.amount.startsWith("-");
  return (
    <>
      <div className="box bad">
        <span className="small medium bad">No invoice yet</span>
        <span>{income ? "No sales invoice is matched to this payment yet." : "Without an invoice this cost can't go into the books, and its VAT can't be reclaimed."}</span>
      </div>
      <DropZone onFile={onFile} />
      <div className="stack" style={{ gap: 6 }}>
        <span className="small medium">Other ways to add it</span>
        <span className="small t2">{mailbox ? <>Forward the invoice e-mail to <span className="medium">{mailbox}</span>. Ordo matches it to this payment by itself.</> : "Forward the invoice e-mail to the company's invoices mailbox. Ordo matches it to this payment by itself."}</span>
      </div>
    </>
  );
}

export function DropZone({ onFile, compact }: { onFile: (f: File) => void; compact?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  }
  const picker = <input ref={input} type="file" accept="image/*,application/pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />;
  if (compact) return <>{picker}<button type="button" className="quiet" onClick={() => input.current?.click()}>Replace</button></>;
  return (
    <div className={`drop${over ? " over" : ""}`} role="button" tabIndex={0} onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
      {picker}
      <span className="accent" aria-hidden="true"><Icon name="upload" size={22} /></span>
      <span className="medium">Drop a photo or PDF here</span>
      <span className="small accent">or choose a file</span>
      <span className="small t3">Ordo reads it and fills in the details for you.</span>
    </div>
  );
}

/** What Ordo read from a file, before the owner confirms it. */
function ReadResult({ p, d, onChanged }: { p: Payment; d: OrdoDocument; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conf = d.extraction.field_confidence ?? {};
  const unsure = (k: string) => typeof conf[k] === "number" && conf[k] < LOW_CONFIDENCE;
  const rows: [string, string, string][] = [
    ["seller", "Seller", plainName(d.seller.name)],
    ["seller_tax_id", "Seller tax no.", d.seller.tax_id ?? "Not found"],
    ["buyer_tax_id", "Our tax no. on it", d.buyer.tax_id ?? "None"],
    ["issue_date", "Date", d.issue_date ? longDate(d.issue_date) : "Not found"],
    ["gross", "Total", formatMoney(d.totals.gross)],
    ["vat", "VAT", d.totals.vat ? formatMoney(d.totals.vat) : "Not found"],
    ["number", "Invoice no.", d.number ?? "Not found"],
  ];
  const DOUBT: Record<string, string> = { seller: "seller", seller_tax_id: "seller's tax number", buyer_tax_id: "tax number", issue_date: "date", gross: "total", vat: "VAT", number: "invoice number" };
  const doubts = rows.filter(([k]) => unsure(k)).map(([k]) => DOUBT[k]);
  async function confirm() {
    if (!p.match) return;
    setBusy(true);
    setError(null);
    try {
      await api.decideMatch(p.match.id, { decision: "approved", channel: "dashboard" });
      onChanged();
      requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }
  return (
    <>
      <div className="box good">
        <StatusLabel level="analysed_autonomously" />
        <span>{d.channel === "upload" ? "Ordo read the invoice you added. Check the details, then confirm." : "Ordo matched an invoice to this payment. Check it, then confirm."}</span>
      </div>
      <div className="hstack" style={{ alignItems: "flex-start", gap: 16, flexWrap: "nowrap" }}>
        <Slip d={d} />
        <div className="stack grow" style={{ gap: 4 }}>
          {rows.map(([k, label, value]) => <div key={k} className={`kv${unsure(k) ? " flag" : ""}`}><span className="t2">{label}</span><span className={k === "buyer_tax_id" && d.buyer.is_company ? "good" : undefined}>{value}</span></div>)}
          {doubts.length > 0 && <span className="small warn">Please check the {doubts.join(" and ")}. Ordo is not sure it read {doubts.length === 1 ? "it" : "them"} right.</span>}
        </div>
      </div>
      {d.totals.vat && <span className={`small ${d.buyer.is_company ? "good" : "bad"}`}>{d.buyer.is_company ? `Our tax number is on it, so the ${formatMoney(d.totals.vat)} of VAT can be reclaimed.` : `Without our tax number the ${formatMoney(d.totals.vat)} of VAT can't be reclaimed.`}</span>}
      {error && <span className="small bad" role="alert">Not confirmed: {error}</span>}
      <div className="hstack">
        <button type="button" className="primary" disabled={busy || !p.match} onClick={confirm}>{busy ? "Saving…" : "Looks right"}</button>
        <Link to={`/documents/${d.id}`} className="button">Fix a field</Link>
      </div>
      {!p.match && <span className="small t3">Ordo is still matching it to the payment.</span>}
      <span className="small t3">Read by the AI model on our cluster. Only details you confirm go into the books.</span>
    </>
  );
}

function OnFile({ p, onFile }: { p: Payment; onFile: (f: File) => void }) {
  const d = p.document;
  if (!d) return <div className="box plain"><span className="small">{p.doc === "receipt" ? "Receipt" : "Invoice"} on file.</span></div>;
  // Once the owner confirmed the document, "Ordo was unsure" is no longer news.
  const notes = flagNotes(d, p.match ?? undefined).filter((n) => !(d.status === "approved" && n === "Low confidence"));
  return (
    <div className="stack" style={{ gap: 12 }}>
      <span className="small medium">{d.doc_type === "receipt" ? "Receipt" : "Invoice"}</span>
      <div className="hstack" style={{ alignItems: "flex-start", gap: 16, flexWrap: "nowrap" }}>
        <Slip d={d} />
        <div className="stack grow" style={{ gap: 6 }}>
          <div className="kv"><span className="t2">Seller tax no.</span><span>{d.seller.tax_id ?? "Not found"}</span></div>
          <div className="kv"><span className="t2">VAT on it</span><span>{d.totals.vat ? formatMoney(d.totals.vat) : "—"}</span></div>
          <div className="kv"><span className="t2">Our tax no. on it</span><span className={d.buyer.tax_id ? undefined : "bad"}>{d.buyer.tax_id ?? "None"}</span></div>
          {notes.map((n) => <span key={n} className="small bad">{n}</span>)}
        </div>
      </div>
      <div className="hstack">
        <Link to={`/documents/${d.id}`} className="button quiet">Open</Link>
        <DropZone onFile={onFile} compact />
      </div>
    </div>
  );
}

/** A small picture of the document: the original file when the API serves it, else drawn from what was read. */
function Slip({ d }: { d: OrdoDocument }) {
  const url = d.raw_item_ids[0] ? rawContentUrl(d.raw_item_ids[0]) : null;
  if (url && (d.channel === "photo" || d.channel === "upload")) return <div className="slip"><img src={url} alt={`${d.doc_type} from ${plainName(d.seller.name)}`} /></div>;
  return (
    <div className="slip" aria-hidden="true">
      <span className="medium">{plainName(d.seller.name).toUpperCase()}</span>
      {d.seller.tax_id && <span>NIP {d.seller.tax_id}</span>}
      {d.number && <span>{d.number}</span>}
      {d.issue_date && <span>{d.issue_date}</span>}
      {(d.lines ?? []).slice(0, 3).map((l) => <span key={l.description}>{l.quantity ?? 1} × {l.description}</span>)}
      <span className="medium">SUMA {d.totals.gross.currency} {d.totals.gross.amount}</span>
      {d.totals.vat && <span>VAT {d.totals.vat.amount}</span>}
      {d.payment?.card_last4 && <span>Karta ****{d.payment.card_last4}</span>}
    </div>
  );
}

const CHANGEABLE = Object.keys(CATEGORY_LABEL).filter((c) => c !== "revenue_services") as Category[];

/** Why the payment sits under its type, and a way to change it when there is a document to correct. */
function Why({ p, onChanged }: { p: Payment; onChanged: () => void }) {
  const t = typeOf(p);
  const d = p.document;
  const suggestion = d?.category_suggestion;
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { companyId } = useCompany();
  const t0 = p.transaction;
  async function change(category: Category) {
    setError(null);
    try {
      // With a document the correction goes on it; a bank line alone gets its type changed directly.
      // Either way the backend remembers it as a rule for this counterparty.
      if (d) await api.patchDocument(d.id, { category_suggestion: { category, confidence: 1, method: "history" } });
      else if (t0 && (await api.setTransactionCategory(t0.id, category, companyId)) === null) {
        return setError("Not saved: the backend cannot change a payment's type yet.");
      }
      setEditing(false);
      onChanged();
      requestRefresh();
    } catch (e) {
      setError(`Not saved: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  const reasons = (p.match?.reasons ?? []).slice(0, 2).map((r) => r.detail);
  const paid = p.match ? whoPaid(p.match) : null;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="hstack"><span className="small grow">Why Ordo put it here</span><StatusLabel level="analysed_autonomously" /></div>
      <div className="hstack" style={{ flexWrap: "nowrap" }}>
        <span className="dot" style={{ background: t.color }} />
        <span className="medium">{t.label}</span>
        <span className="small t3 grow">
          {suggestion && suggestion.confidence < 1 ? `${Math.round(suggestion.confidence * 100)}% sure` : ""}
          {p.category && t.label !== categoryLabel(p.category) ? `${suggestion && suggestion.confidence < 1 ? " · " : ""}${categoryLabel(p.category).toLowerCase()}` : ""}
          {d?.lines?.[0] && p.doc === "to_check" ? ` · ${d.lines[0].description.toLowerCase()}` : ""}
        </span>
        {(d || t0) && !editing && <button type="button" className="quiet" onClick={() => setEditing(true)}>{p.category && p.category !== "other" ? "Change" : "Choose a type"}</button>}
      </div>
      {editing && (d || t0) && (
        <label className="pill-select">
          <select aria-label="Type" defaultValue={suggestion?.category ?? p.category ?? "other"} onChange={(e) => change(e.target.value as Category)}>
            {CHANGEABLE.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}
          </select>
        </label>
      )}
      {error && <span className="small bad" role="alert">{error}</span>}
      {paid && p.match?.paid_by !== "company_account" && <span className="small t2">{paid.headline}{p.match?.payer?.email ? `: the receipt came from ${firstName(p.match.payer.name)}'s e-mail` : ""}.</span>}
      {reasons.map((r) => <span key={r} className="small t2">{r}</span>)}
      {!d && p.doc === "missing" && <span className="small t2">No invoice{p.category === "other" ? ", and no rule for this shop yet" : ""}. Once you choose a type, Ordo remembers it for {p.name}.</span>}
      {!d && p.doc !== "missing" && p.transaction && <span className="small t2">From the bank line “{p.transaction.counterparty_name_raw ?? p.transaction.description}”.</span>}
      {d && (
        <div className="hstack">
          <Link to={`/documents/${d.id}`} className="chip info">{d.doc_type === "receipt" ? "Receipt photo" : "Invoice"}</Link>
          {p.match?.payer?.name && <span className="chip info">{firstName(p.match.payer.name)}'s e-mail</span>}
        </div>
      )}
    </div>
  );
}
