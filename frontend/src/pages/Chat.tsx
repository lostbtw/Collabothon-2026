import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, type ChatAnswer } from "../api/client";
import { ControlBadges } from "../components/ControlBadges";
import { Evidence, More, MoreGroup } from "../components/More";
import { useCompany } from "../lib/company";
import { requestRefresh } from "../lib/refresh";

export type Turn = { question: string; answer: ChatAnswer };

/** Suggested questions per demo company; the first one for any other company. */
export const SUGGESTIONS: Record<string, string[]> = {
  co_borsuk: ["Why will I be short in December?", "What do I owe the team?", "Which subscriptions went up?"],
  co_amalfi: ["We are closed for all of June", "How much cash do I have?", "What are my biggest costs?"],
};

export function Chat() {
  const { companyId } = useCompany();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await api.chat(question, companyId, turns.at(-1)?.answer.session_id);
      setTurns((t) => [...t, { question, answer }]);
      // Chat can propose a card or record a plan: let the shell and other screens re-read.
      if (answer.created_recommendation_id || answer.tool_calls?.length) requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return <ChatView key={companyId} turns={turns} busy={busy} error={error} onSend={send} suggestions={SUGGESTIONS[companyId] ?? SUGGESTIONS.co_borsuk} />;
}

export function ChatView({ turns, busy, error, onSend, suggestions }: { turns: Turn[]; busy: boolean; error: string | null; onSend: (question: string) => void; suggestions: string[] }) {
  const [message, setMessage] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    onSend(message);
    setMessage("");
  }
  return (
    <>
      <h1>Ask Ordo</h1>
      <div className="card chat">
        {turns.map((t, i) => <TurnView key={i} turn={t} />)}
        {busy && <p className="muted">Thinking…</p>}
        {error && <p className="danger" role="alert">No answer: {error}</p>}
        <div className="hstack">
          {suggestions.map((s) => <button key={s} type="button" className="outline" disabled={busy} onClick={() => onSend(s)}>{s}</button>)}
        </div>
        <form onSubmit={submit} className="composer">
          <input type="text" aria-label="Your question" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask about your money" />
          <button className="primary" type="submit" disabled={busy || !message.trim()}>Send</button>
        </form>
      </div>
    </>
  );
}

function TurnView({ turn: { question, answer: a } }: { turn: Turn }) {
  const calls = a.tool_calls ?? [];
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="bubble">{question}</div>
      {a.guardrail?.blocked
        ? <div className="note">{a.guardrail.reason}</div>
        : <p className="body15">{a.answer}</p>}
      {a.table && a.table.rows.length > 0 && (
        <table className="answer-table">
          <thead><tr>{a.table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{a.table.rows.map((r, i) => <tr key={i}>{r.map((cell, j) => <td key={j}>{String(cell ?? "")}</td>)}</tr>)}</tbody>
        </table>
      )}
      {a.created_recommendation_id && (
        <div className="hstack">
          <ControlBadges level="approval_required" execution="simulated" />
          <Link to={`/inbox/${a.created_recommendation_id}`} className="chip">Open the card in your inbox</Link>
        </div>
      )}
      {a.evidence.length > 0 && <Evidence links={a.evidence} />}
      {(calls.length > 0 || a.table?.sql) && (
        <MoreGroup>
          <More title="How I got this" count={calls.length || undefined}>
            {calls.map((c, i) => <p key={i} className="small tertiary">{c.tool.replaceAll("_", " ")} · {c.duration_ms} ms</p>)}
            {a.table?.sql && <code>{a.table.sql}</code>}
            {a.trace_id && <p className="small tertiary">Trace {a.trace_id}</p>}
            <p className="small tertiary">Numbers come from the finance engine; the model only writes the sentence.</p>
          </More>
        </MoreGroup>
      )}
    </div>
  );
}
