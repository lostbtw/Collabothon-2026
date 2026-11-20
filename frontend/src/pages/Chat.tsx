import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { api, type ChatAnswer } from "../api/client";
import { ControlBadges } from "../components/ControlBadges";
import { Icon } from "../components/Icon";
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
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A conversation belongs to one company: switching company starts a new one.
  useEffect(() => { setTurns([]); setPending(null); setError(null); }, [companyId]);

  async function send(question: string) {
    if (!question.trim() || pending) return;
    setPending(question);
    setError(null);
    try {
      const answer = await api.chat(question, companyId, turns.at(-1)?.answer.session_id);
      setTurns((t) => [...t, { question, answer }]);
      // Chat can propose a card or record a plan: let the shell and other screens re-read.
      if (answer.created_recommendation_id || answer.tool_calls?.length) requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }
  return <ChatView turns={turns} pending={pending} busy={pending !== null} error={error} onSend={send} onNew={() => { setTurns([]); setError(null); }} suggestions={SUGGESTIONS[companyId] ?? SUGGESTIONS.co_borsuk} />;
}

type ViewProps = { turns: Turn[]; busy: boolean; error: string | null; onSend: (question: string) => void; suggestions: string[]; pending?: string | null; onNew?: () => void };

/**
 * Laid out like a chat app: an empty chat is a greeting with the input in the middle of the page;
 * once there are messages they run down a centred column and the input stays at the bottom.
 */
export function ChatView({ turns, busy, error, onSend, suggestions, pending, onNew }: ViewProps) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [turns.length, pending, error]);

  if (turns.length === 0 && !busy && !error) {
    return (
      <div className="chat-page">
        <div className="chat-empty">
          <h1>What do you want to know?</h1>
          <Composer busy={busy} onSend={onSend} autoFocus />
          <div className="hstack" style={{ justifyContent: "center" }}>
            {suggestions.map((s) => <button key={s} type="button" className="outline" onClick={() => onSend(s)}>{s}</button>)}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="chat-page">
      <div className="chat-head">
        <span className="tertiary">Ask Ordo</span>
        {onNew && <button type="button" className="outline" disabled={busy} onClick={onNew}>New chat</button>}
      </div>
      <div className="chat-thread">
        {turns.map((t, i) => <TurnView key={i} turn={t} />)}
        {pending && (
          <>
            <div className="bubble">{pending}</div>
            <div className="typing" role="status" aria-label="Ordo is answering"><span /><span /><span /></div>
          </>
        )}
        {error && <p className="danger" role="alert">No answer: {error}</p>}
        <div ref={end} />
      </div>
      <div className="chat-dock">
        <Composer busy={busy} onSend={onSend} />
        <p className="caption muted">Numbers come from the finance engine. Ordo cannot move money from chat.</p>
      </div>
    </div>
  );
}

function Composer({ busy, onSend, autoFocus }: { busy: boolean; onSend: (question: string) => void; autoFocus?: boolean }) {
  const [message, setMessage] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!message.trim() || busy) return;
    onSend(message.trim());
    setMessage("");
    if (box.current) box.current.style.height = "auto";
  }
  // Enter sends, Shift+Enter makes a new line.
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }
  function grow(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }
  return (
    <form onSubmit={submit} className="composer">
      <textarea ref={box} rows={1} autoFocus={autoFocus} aria-label="Message Ordo" placeholder="Ask about your money" value={message}
        onChange={(e) => { setMessage(e.target.value); grow(e.target); }} onKeyDown={onKey} />
      <button className="primary send" type="submit" disabled={busy || !message.trim()} aria-label="Send"><Icon name="arrowUp" size={18} /></button>
    </form>
  );
}

function TurnView({ turn: { question, answer: a } }: { turn: Turn }) {
  const calls = a.tool_calls ?? [];
  return (
    <>
      <div className="bubble">{question}</div>
      <div className="answer">
        {a.guardrail?.blocked
          ? <div className="note">{a.guardrail.reason}</div>
          : <p>{a.answer}</p>}
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
            </More>
          </MoreGroup>
        )}
      </div>
    </>
  );
}
