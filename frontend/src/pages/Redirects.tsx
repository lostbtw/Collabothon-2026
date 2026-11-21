import { Navigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { useApi } from "../lib/useApi";

export function MatchRedirect() {
  const { id = "" } = useParams();
  const state = useApi(() => api.matches().then((m) => m.items.find((x) => x.id === id) ?? null), [id]);
  return <PageState state={state}>{(match) => (match ? <Navigate to={`/documents/${match.document_id}`} replace /> : null)}</PageState>;
}
