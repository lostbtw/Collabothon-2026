import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { isRenderableRecommendation } from "../api/guards";
import { ControlBadges } from "../components/ControlBadges";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { useApi } from "../lib/useApi";

export function Inbox() {
  const { companyId } = useCompany();
  const state = useApi(() => api.inbox(companyId), [companyId]);
  return (
    <>
      <h1>Inbox</h1>
      <PageState state={state} empty={(d) => d.items.length === 0}>
        {(inbox) => (
          <div className="stack">
            <p className="muted">{inbox.counts.approval_required} need your approval · {inbox.counts.recommendation} recommendation(s)</p>
            {/* Cards without control level, execution mode, explanation and evidence are not shown (contracts rule 4). */}
            {inbox.items.filter(isRenderableRecommendation).map((r) => (
              <Link key={r.id} to={`/inbox/${r.id}`} className="card link">
                <ControlBadges level={r.control_level} execution={r.execution_mode} />
                <h2>{r.title}</h2>
                <p className="muted">{r.summary}</p>
              </Link>
            ))}
          </div>
        )}
      </PageState>
    </>
  );
}

export function InboxDetail() {
  const { id = "" } = useParams();
  const state = useApi(() => api.recommendation(id), [id]);
  return (
    <PageState state={state} empty={(r) => !isRenderableRecommendation(r)}>
      {(r) => (
        <div className="card stack">
          <ControlBadges level={r.control_level} execution={r.execution_mode} />
          <h1>{r.title}</h1>
          <p>{r.summary}</p>
          <h2>Why?</h2>
          <ul className="plain">{r.explanation.why.map((w) => <li key={w}>{w}</li>)}</ul>
          <h2>Evidence</h2>
          <ul className="plain">{r.evidence.map((e) => <li key={e.kind + e.id}>{e.url ? <Link to={e.url}>{e.label}</Link> : e.label}</li>)}</ul>
          <p><Link to="/inbox">Back to inbox</Link></p>
        </div>
      )}
    </PageState>
  );
}
