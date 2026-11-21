// Small building blocks shared by every screen, matching the components in Figma ("Ordo · new design").
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import type { ControlLevel, Money } from "../api/types.gen";
import { compareAmounts, isZero, monthName, subtract } from "../lib/costTypes";
import { whole } from "../lib/words";
import { useAsk } from "./AskOrdo";
import { Icon } from "./Icon";

/** Page title, one plain line under it, and the Ask Ordo button on the right. */
export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {children ?? <AskButton />}
    </div>
  );
}

export function AskButton({ draft }: { draft?: string }) {
  const ask = useAsk();
  return <button type="button" className="primary" onClick={() => ask.open(draft)}><Icon name="chat" size={16} />Ask Ordo</button>;
}

const LEVEL: Record<ControlLevel | "approved", [string, string]> = {
  approval_required: ["Needs your OK", "ok-needed"],
  recommendation: ["Suggestion", "suggestion"],
  analysed_autonomously: ["Done by Ordo", "by-ordo"],
  approved: ["Approved by you", "approved"],
};

/** The control level in plain words (product rule: every agent output shows it). */
export function StatusLabel({ level }: { level: ControlLevel | "approved" }) {
  const [text, cls] = LEVEL[level];
  return <span className={`status ${cls}`}>{text}</span>;
}

/** A number tile: label, the number, one short note. */
export function Tile({ label, value, note, tone, to }: { label: string; value: ReactNode; note?: ReactNode; tone?: "good" | "bad" | "warn"; to?: string }) {
  const body = (
    <>
      <span className="label-text">{label}</span>
      <span className="number">{value}</span>
      {note && <span className={`small${tone ? ` ${tone}` : " t2"}`}>{note}</span>}
    </>
  );
  return to ? <Link to={to} className="card tile">{body}</Link> : <div className="card tile">{body}</div>;
}

/** "↑ 14,100 PLN vs September". `upIsGood` decides the colour: more income is good, more costs are not.
 * Leave out `vs` where the section already says what it is compared with. */
export function Change({ now, before, upIsGood, vs }: { now: Money; before: Money | null; upIsGood: boolean; vs?: string }) {
  if (!before) return null;
  const diff = subtract(now.amount, before.amount);
  if (isZero(diff)) return <span className="small t2">{vs ? `Same as ${vs}` : "No change"}</span>;
  const up = compareAmounts(diff, "0") > 0;
  return (
    <span className={`small ${up === upIsGood ? "good" : "bad"}`}>
      {up ? "↑" : "↓"} {whole({ amount: diff.replace("-", ""), currency: now.currency })}{vs ? ` vs ${vs}` : ""}
    </span>
  );
}

/** Month picker. `look="section"` is the large inline one used as a section title. */
export function MonthSelect({ value, months, onChange, look = "pill", allowAll }: { value: string; months: string[]; onChange: (month: string) => void; look?: "pill" | "section"; allowAll?: boolean }) {
  const options = value === "" || months.includes(value) ? months : [value, ...months];
  const label = value === "" ? "All months" : monthName(value);
  return (
    <label className={`pill-select${look === "section" ? " section-select" : ""}`}>
      {/* The visible text is the chosen month; the select over it keeps its own width out of the layout. */}
      <span className="pill-label">{label}</span>
      <select aria-label="Month" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowAll && <option value="">All months</option>}
        {options.map((m) => <option key={m} value={m}>{monthName(m)}</option>)}
      </select>
      <Icon name="chevron" size={14} />
    </label>
  );
}

/** What a screen shows when the backend does not send a piece of data (yet). */
export function Waiting({ what, children }: { what: string; children?: ReactNode }) {
  return (
    <div className="card waiting">
      <span className="medium">Ordo can't show {what} yet</span>
      <span className="small t2">The backend does not send it for this company yet.{children ? " " : ""}{children}</span>
    </div>
  );
}

/** A switch. Without `onChange` it only shows a state the owner cannot change in this build. */
export function Toggle({ on, onChange, label }: { on: boolean; onChange?: (on: boolean) => void; label: string }) {
  if (!onChange) return <span className={`toggle${on ? " on" : ""}`} role="img" aria-label={`${label}: ${on ? "on" : "off"}`}><i /></span>;
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className={`toggle${on ? " on" : ""}`} onClick={() => onChange(!on)}>
      <i />
    </button>
  );
}

export function Avatar({ text }: { text: string }) {
  return <span className="avatar" aria-hidden="true">{text}</span>;
}

/** A button that runs an action in the sandbox bank. It says so with a small tag (product rule: the word
 * "simulated" on the button), and its tooltip says what will happen. */
export function SimButton({ label, onClick, busy, disabled, primary = true, what }: {
  label: string; onClick: () => void; busy?: boolean; disabled?: boolean; primary?: boolean; what?: string | null;
}) {
  return (
    <button type="button" className={primary ? "primary" : undefined} disabled={busy || disabled} onClick={onClick}
      title={what ?? "Runs in the test bank only. No real money moves."}>
      {busy ? "Working…" : label}<span className="sim-tag">simulated</span>
    </button>
  );
}

/** A row's chevron, pointing to where its details are. */
export function Chevron() {
  return <span className="chev" aria-hidden="true"><Icon name="chevronRight" size={16} /></span>;
}

/** The close button of a panel. */
export function CloseButton({ onClick }: { onClick: () => void }) {
  return <button type="button" className="quiet icon-button" aria-label="Close" onClick={onClick}><Icon name="close" size={16} /></button>;
}

/** Grey placeholders shaped like the content that is loading, instead of a "Loading…" line. */
export function Skeleton({ rows = 3, tiles = 0, title = false }: { rows?: number; tiles?: number; title?: boolean }) {
  return (
    <div className="stack" style={{ gap: 16 }} aria-busy="true" aria-label="Loading">
      {tiles > 0 && (
        <div className="row">
          {Array.from({ length: tiles }, (_, i) => <div key={i} className="card tile"><span className="skeleton line" style={{ width: "40%" }} /><span className="skeleton big" /></div>)}
        </div>
      )}
      {rows > 0 && (
        <div className="card stack" style={{ gap: 18 }}>
          {title && <span className="skeleton line" style={{ width: "30%", height: 16 }} />}
          {Array.from({ length: rows }, (_, i) => <span key={i} className="skeleton line" style={{ width: `${88 - (i % 3) * 14}%` }} />)}
        </div>
      )}
    </div>
  );
}

/** Index for the 30 ms row stagger (styles/app.css). */
export const nth = (i: number): CSSProperties => ({ "--i": i }) as CSSProperties;

/** Navigation tabs whose white pill slides to the chosen tab (the same object moves, it does not jump). */
export function SlidingTabs({ items, active, label }: { items: { key: string; label: string; to: string }[]; active: string; label: string }) {
  const box = useRef<HTMLElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const el = box.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(active)}"]`);
    if (el) setPill({ x: el.offsetLeft, w: el.offsetWidth });
  }, [active, items.length]);
  return (
    <nav ref={box} className={`tabs${pill ? " sliding" : ""}`} aria-label={label}>
      {pill && <span className="tabs-pill" style={{ width: pill.w, transform: `translateX(${pill.x}px)` }} />}
      {items.map((x) => <NavLink key={x.key} data-key={x.key} to={x.to} end className={() => (x.key === active ? "on" : "")}>{x.label}</NavLink>)}
    </nav>
  );
}
