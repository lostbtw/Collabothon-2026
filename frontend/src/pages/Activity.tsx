import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ControlBadges } from "../components/ControlBadges";
import { PageState } from "../components/PageState";
import { useCompany } from "../lib/company";
import { useApi } from "../lib/useApi";

export function Activity() {
  const { companyId } = useCompany();
  const state = useApi(() => api.activity(companyId), [companyId]);
  return (
    <>
      <h1>What I did on my own</h1>
      <PageState state={state} empty={(d) => d.items.length === 0}>
        {(activity) => (
          <div className="stack">
            {activity.items.map((a) => (
              <div key={a.at + a.text} className="card">
                <ControlBadges level="analysed_autonomously" />
                <p>{a.text}</p>
                <p className="small">{a.evidence.map((e) => (e.url ? <Link key={e.id} to={e.url}>{e.label}</Link> : <span key={e.id}>{e.label}</span>))}</p>
              </div>
            ))}
          </div>
        )}
      </PageState>
    </>
  );
}
