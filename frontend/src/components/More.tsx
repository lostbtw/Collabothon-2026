import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { EvidenceLink } from "../api/types.gen";

export function MoreGroup({ children }: { children: ReactNode }) {
  return <div className="more">{children}</div>;
}

export function More({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <details>
      <summary>{title}{count !== undefined && <span className="muted">{count}</span>}</summary>
      <div className="more-body">{children}</div>
    </details>
  );
}

export function Evidence({ links }: { links: EvidenceLink[] }) {
  return (
    <div className="hstack">
      {links.map((e) => (e.url ? <Link key={e.kind + e.id} to={e.url} className="chip">{e.label}</Link> : <span key={e.kind + e.id} className="chip neutral">{e.label}</span>))}
    </div>
  );
}
