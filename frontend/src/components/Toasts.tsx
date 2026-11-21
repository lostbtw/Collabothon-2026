import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Money, OrdoEvent } from "../api/types.gen";
import { useLive } from "../lib/live";
import { formatMoney } from "../lib/money";
import { requestRefresh } from "../lib/refresh";

export type Toast = { id: string; text: string; to?: string; leaving?: boolean };
/** Same as --t-exit in styles/app.css: a toast fades out before it is removed. */
const EXIT_MS = 160;

const isMoney = (v: unknown): v is Money => typeof v === "object" && v !== null && typeof (v as Money).amount === "string";
const first = (name?: string | null) => (name ?? "").split(" ")[0];

/**
 * What a live event says to the owner, or null when it needs no toast. `sender` is the person who
 * sent the document, when known. Amounts are copied from the event, never calculated.
 */
export function toastFor(e: OrdoEvent, sender?: string | null): Toast | null {
  const p = e.payload;
  if (e.type === "document.extracted" && typeof p.document_id === "string") {
    const from = first(sender) || (typeof p.seller === "string" ? p.seller : "");
    return { id: e.id, text: `New receipt${from ? ` from ${from}` : ""}${isMoney(p.gross) ? ` · ${formatMoney(p.gross)}` : ""}`, to: `/documents/${p.document_id}` };
  }
  if (e.type === "recommendation.created" && typeof p.recommendation_id === "string") return { id: e.id, text: "New to-do", to: `/todo#${p.recommendation_id}` };
  if (e.type === "forecast.updated" && isMoney(p.min_balance)) {
    const was = isMoney(p.min_balance_previous) ? ` (was ${formatMoney(p.min_balance_previous, { decimals: false })})` : "";
    return { id: e.id, text: `Forecast updated: lowest point ${formatMoney(p.min_balance, { decimals: false })}${was}`, to: "/#cash" };
  }
  return null;
}

/** Events after which counters and lists on screen are out of date. */
const REFRESH: ReadonlySet<OrdoEvent["type"]> = new Set(["recommendation.created", "recommendation.status_changed", "forecast.updated", "document.extracted", "approval.recorded", "execution.simulated", "sync.run.finished"]);

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: string) => {
    setToasts((list) => list.map((x) => (x.id === id ? { ...x, leaving: true } : x)));
    setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), EXIT_MS);
  }, []);
  const show = useCallback((t: Toast) => {
    setToasts((list) => [...list.filter((x) => x.id !== t.id), t].slice(-3));
    setTimeout(() => dismiss(t.id), 7000);
  }, [dismiss]);

  useLive((e) => {
    if (REFRESH.has(e.type)) requestRefresh();
    if (e.type === "document.extracted" && typeof e.payload.document_id === "string") {
      // The event carries no sender; the document does.
      void api.document(e.payload.document_id).then((d) => d.document.submitted_by?.name, () => null).then((name) => { const t = toastFor(e, name); if (t) show(t); });
      return;
    }
    const t = toastFor(e);
    if (t) show(t);
  });

  return <ToastList toasts={toasts} onClose={dismiss} />;
}

export function ToastList({ toasts, onClose }: { toasts: Toast[]; onClose: (id: string) => void }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.leaving ? " leaving" : ""}`}>
          {t.to ? <Link to={t.to} onClick={() => onClose(t.id)}>{t.text}</Link> : <span>{t.text}</span>}
          <button type="button" className="linklike" aria-label="Dismiss" onClick={() => onClose(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
