// The sources behind a chat answer: a few chips, the rest in a popover grouped by kind.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { EvidenceLink } from "../api/types.gen";

/** How many sources show as chips before "+N more". */
export const VISIBLE_SOURCES = 3;

const KIND_LABEL: Record<EvidenceLink["kind"], string> = {
  forecast: "Forecast", forecast_component: "Forecast", recommendation: "To-dos", document: "Invoices and receipts",
  match: "Matches", transaction: "Payments", ledger_entry: "Books", raw_item: "Files", rule: "Rules", fx_rate: "Exchange rates",
  sql: "Queries", external: "Other",
};
const KIND_ORDER: EvidenceLink["kind"][] = ["forecast", "forecast_component", "recommendation", "document", "match", "transaction",
  "ledger_entry", "fx_rate", "rule", "raw_item", "sql", "external"];

/** Links can be absolute (the backend's own host); inside the app they open as app routes. */
export function appPath(url: string): string {
  try {
    return url.startsWith("/") ? url : new URL(url).pathname + new URL(url).search;
  } catch {
    return url;
  }
}

/** Sources grouped by kind, in a fixed order; account links count as payments' context and go under "Accounts". */
export function groupSources(links: EvidenceLink[]): { label: string; links: EvidenceLink[] }[] {
  const isAccount = (l: EvidenceLink) => /\/accounts\//.test(l.url ?? "");
  const groups = new Map<string, EvidenceLink[]>();
  const add = (label: string, l: EvidenceLink) => groups.set(label, [...(groups.get(label) ?? []), l]);
  for (const l of links.filter(isAccount)) add("Accounts", l);
  for (const kind of KIND_ORDER) for (const l of links.filter((x) => x.kind === kind && !isAccount(x))) add(KIND_LABEL[kind], l);
  return [...groups.entries()].map(([label, items]) => ({ label, links: items }));
}

function Chip({ link }: { link: EvidenceLink }) {
  return link.url ? <Link to={appPath(link.url)} className="chip">{link.label}</Link> : <span className="chip neutral">{link.label}</span>;
}

export function Sources({ links }: { links: EvidenceLink[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", esc, true);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", esc, true); };
  }, [open]);
  if (links.length === 0) return null;
  const shown = links.slice(0, VISIBLE_SOURCES);
  const rest = links.length - shown.length;
  return (
    <div className="hstack sources" ref={box}>
      {shown.map((l) => <Chip key={l.kind + l.id} link={l} />)}
      {rest > 0 && (
        <button type="button" className="chip more-sources" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide sources" : `+${rest} more source${rest === 1 ? "" : "s"}`}
        </button>
      )}
      {open && (
        <div className="sources-pop" role="dialog" aria-label={`All ${links.length} sources`}>
          <span className="small medium">All {links.length} sources</span>
          {groupSources(links).map((g) => (
            <div key={g.label} className="stack" style={{ gap: 6 }}>
              <span className="caption t3">{g.label} · {g.links.length}</span>
              <div className="hstack">{g.links.map((l) => <Chip key={l.kind + l.id} link={l} />)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
