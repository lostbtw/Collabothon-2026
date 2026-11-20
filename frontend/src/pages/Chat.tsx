import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, type ChatAnswer } from "../api/client";
import { useCompany } from "../lib/company";

export function Chat() {
  const { companyId } = useCompany();
  const [message, setMessage] = useState("Why will I be short in December?");
  const [turns, setTurns] = useState<{ question: string; answer: ChatAnswer }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!message.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await api.chat(message, companyId, turns.at(-1)?.answer.session_id);
      setTurns((t) => [...t, { question: message, answer }]);
      setMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Chat</h1>
      <div className="stack">
        {turns.map((t, i) => (
          <div key={i} className="card stack">
            <p className="muted">{t.question}</p>
            <p>{t.answer.answer}</p>
            <p className="small">{t.answer.evidence.map((ev) => (ev.url ? <Link key={ev.id} to={ev.url}>{ev.label}</Link> : <span key={ev.id}>{ev.label}</span>))}</p>
          </div>
        ))}
        {error && <p className="danger" role="alert">Could not get an answer: {error}</p>}
        <form onSubmit={send} className="row">
          <input type="text" aria-label="Your question" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask about your money in plain words" />
          <button className="primary" type="submit" disabled={busy}>{busy ? "Asking…" : "Ask"}</button>
        </form>
      </div>
    </>
  );
}
