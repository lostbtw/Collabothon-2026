// Ask Ordo: a chat panel that slides in over any page, with the company's past chats on the left.
// Past chats come from GET /chat/sessions; until the backend serves it, the panel keeps this tab's chats.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type ChatAnswer, type ChatSession } from "../api/client";
import { useCompany, useToday } from "../lib/company";
import { daysBetween, shortDate } from "../lib/dates";
import { requestRefresh } from "../lib/refresh";
import { Icon } from "./Icon";
import { Sources } from "./Sources";
import { CloseButton } from "./ui";

/** Same as --t-exit in styles/app.css. */
const EXIT_MS = 160;

const AskContext = createContext<{ open: (draft?: string) => void }>({ open: () => {} });
export const useAsk = () => useContext(AskContext);

/** Suggested questions per demo company; the first list for any other company. */
export const SUGGESTIONS: Record<string, string[]> = {
  co_borsuk: ["Why are costs up?", "Who still owes us?", "Can I afford a December bonus?"],
  co_amalfi: ["We are closed for all of June", "How much cash do I have?", "What are my biggest costs?"],
};

export function AskProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; draft: string; leaving?: boolean }>({ open: false, draft: "" });
  // Closing plays the exit (slide back to the side the button is on) before the panel leaves the page.
  const close = useCallback(() => {
    setState((s) => ({ ...s, leaving: true }));
    setTimeout(() => setState({ open: false, draft: "" }), EXIT_MS);
  }, []);
  const [params, setParams] = useSearchParams();
  const open = useCallback((draft = "") => setState({ open: true, draft }), []);
  // Old links to /chat arrive as ?ask=1.
  useEffect(() => {
    if (params.get("ask") === "1") {
      open();
      params.delete("ask");
      setParams(params, { replace: true });
    }
  }, [params, setParams, open]);
  return (
    <AskContext.Provider value={{ open }}>
      {children}
      {state.open && <AskPanel draft={state.draft} leaving={Boolean(state.leaving)} onClose={close} />}
    </AskContext.Provider>
  );
}

export type Line = { role: "user"; text: string } | { role: "assistant"; text: string; answer?: ChatAnswer };
type Chat = { id: string; title: string; lastAt: string; lines: Line[] | null };

function AskPanel({ draft, leaving, onClose }: { draft: string; leaving: boolean; onClose: () => void }) {
  const { companyId } = useCompany();
  const today = useToday();
  const [server, setServer] = useState<ChatSession[] | null>(null);
  const [local, setLocal] = useState<Record<string, Chat>>({});
  const [current, setCurrent] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    api.chatSessions(companyId).then((r) => alive && setServer(r?.items ?? null), () => alive && setServer(null));
    return () => { alive = false; };
  }, [companyId, reload]);
  useEffect(() => { setLocal({}); setCurrent(null); }, [companyId]);
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Server chats first (they carry the history), then chats of this tab the server does not know.
  const chats: Chat[] = useMemo(() => {
    const fromServer = (server ?? []).map((s) => ({ id: s.session_id, title: s.title, lastAt: s.last_at, lines: local[s.session_id]?.lines ?? null }));
    const known = new Set(fromServer.map((c) => c.id));
    return [...fromServer, ...Object.values(local).filter((c) => !known.has(c.id))].sort((a, b) => b.lastAt.localeCompare(a.lastAt));
  }, [server, local]);
  const open = chats.find((c) => c.id === current) ?? null;

  async function select(id: string) {
    setCurrent(id);
    setError(null);
    if (local[id]?.lines) return;
    try {
      const detail = await api.chatSession(id, companyId);
      const lines: Line[] = (detail?.messages ?? []).map((m) => ({ role: m.role, text: m.content }));
      const meta = chats.find((c) => c.id === id);
      setLocal((l) => ({ ...l, [id]: { id, title: meta?.title ?? "Chat", lastAt: meta?.lastAt ?? "", lines } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function send(question: string) {
    if (!question.trim() || pending) return;
    setPending(question);
    setError(null);
    try {
      const answer = await api.chat(question, companyId, current);
      const id = answer.session_id;
      setLocal((l) => {
        const before = l[id]?.lines ?? (id === current ? open?.lines : null) ?? [];
        const title = l[id]?.title ?? open?.title ?? question;
        return { ...l, [id]: { id, title, lastAt: new Date().toISOString(), lines: [...before, { role: "user", text: question }, { role: "assistant", text: answer.answer, answer }] } };
      });
      setCurrent(id);
      setReload((n) => n + 1);
      // Chat can propose a to-do or record a plan: let the screens re-read.
      if (answer.created_recommendation_id || answer.tool_calls?.length) requestRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  const lines = open?.lines ?? [];
  const shown = chats.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase()));
  return (
    <>
      <div className={`scrim${leaving ? " leaving" : ""}`} onClick={onClose} />
      <aside className={`ask-panel${leaving ? " leaving" : ""}`} role="dialog" aria-label="Ask Ordo">
        <nav className="history" aria-label="Past chats">
          <button type="button" onClick={() => { setCurrent(null); setError(null); }}><Icon name="plus" size={16} />New chat</button>
          <label className="search"><Icon name="search" size={14} /><input type="search" placeholder="Search chats" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
          {groupChats(shown, today).map(([group, items]) => (
            <div key={group} className="stack" style={{ gap: 2 }}>
              <span className="caption t3 history-group">{group}</span>
              {items.map((c) => (
                <button key={c.id} type="button" className={`history-item${c.id === current ? " on" : ""}`} onClick={() => select(c.id)}>
                  <span className="title">{c.title}</span>
                  <span className="caption t3">{whenLabel(c.lastAt, today)}</span>
                </button>
              ))}
            </div>
          ))}
          <span className="grow" />
          <span className="caption t3">{server ? "Chats are saved for this company only." : "Chats stay in this tab until the backend saves them."}</span>
        </nav>
        <section className="conv">
          <div className="conv-head">
            <span className="medium grow">{open?.title ?? "New chat"}</span>
            <CloseButton onClick={onClose} />
          </div>
          <Thread lines={lines} pending={pending} error={error} onLeave={onClose} />
          <div className="conv-foot">
            <div className="hstack">
              {(SUGGESTIONS[companyId] ?? SUGGESTIONS.co_borsuk).map((s) => <button key={s} type="button" disabled={pending !== null} onClick={() => send(s)}>{s}</button>)}
            </div>
            <Composer key={draft} initial={draft} busy={pending !== null} onSend={send} />
          </div>
        </section>
      </aside>
    </>
  );
}

/** `onLeave` runs when the owner follows an evidence link, so the page it opens is not hidden behind the panel. */
export function Thread({ lines, pending, error, onLeave }: { lines: Line[]; pending: string | null; error: string | null; onLeave?: () => void }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [lines.length, pending, error]);
  return (
    <div className="conv-body" onClick={(e) => { if (onLeave && (e.target as HTMLElement).closest("a")) onLeave(); }}>
      {lines.length === 0 && !pending && (
        <div className="stack" style={{ margin: "auto 0", gap: 4 }}>
          <span className="heading">What do you want to know?</span>
          <span className="t2">Ask about cash, costs, people or clients. Ordo answers from your own numbers.</span>
        </div>
      )}
      {lines.map((l, i) => (l.role === "user" ? <div key={i} className="bubble">{l.text}</div> : <Answer key={i} text={l.text} answer={l.answer} />))}
      {pending && (
        <>
          <div className="bubble">{pending}</div>
          <div className="typing" role="status" aria-label="Ordo is answering"><span /><span /><span /></div>
        </>
      )}
      {error && <p className="danger" role="alert">No answer: {error}</p>}
      {lines.length > 0 && <p className="caption t3">Numbers come from Ordo's calculations. The AI only writes the words.</p>}
      <div ref={end} />
    </div>
  );
}

function Answer({ text, answer: a }: { text: string; answer?: ChatAnswer }) {
  return (
    <div className="answer">
      {a?.guardrail?.blocked ? <div className="note">{a.guardrail.reason}</div> : <p>{text}</p>}
      {a?.table && a.table.rows.length > 0 && (
        <table className="answer-table">
          <thead><tr>{a.table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{a.table.rows.map((r, i) => <tr key={i}>{r.map((cell, j) => <td key={j}>{String(cell ?? "")}</td>)}</tr>)}</tbody>
        </table>
      )}
      {a && a.evidence.length > 0 && <Sources links={a.evidence} />}
    </div>
  );
}

export function Composer({ busy, onSend, initial = "" }: { busy: boolean; onSend: (question: string) => void; initial?: string }) {
  const [message, setMessage] = useState(initial);
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
  return (
    <form onSubmit={submit} className="composer">
      <textarea ref={box} rows={1} autoFocus aria-label="Message Ordo" placeholder="Ask about your money" value={message}
        onChange={(e) => { setMessage(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`; }} onKeyDown={onKey} />
      <button className="primary send" type="submit" disabled={busy || !message.trim()} aria-label="Send"><Icon name="arrowUp" size={18} /></button>
    </form>
  );
}

// Monday-based weeks, so "Last week" means the calendar week before this one.
const weekStart = (iso: string): string => {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
};

/** Today / Yesterday / This week / Last week / Earlier, newest group first. */
export function groupChats<T extends { lastAt: string }>(chats: T[], today: string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const c of chats) {
    const ago = daysBetween(c.lastAt.slice(0, 10), today);
    const weeks = daysBetween(weekStart(c.lastAt), weekStart(today)) / 7;
    const g = ago <= 0 ? "Today" : ago === 1 ? "Yesterday" : weeks === 0 ? "This week" : weeks === 1 ? "Last week" : "Earlier";
    groups.set(g, [...(groups.get(g) ?? []), c]);
  }
  return [...groups.entries()];
}

/** "10:42" today and yesterday, "Fri" within two weeks, "13 Nov" before that. */
export function whenLabel(iso: string, today: string): string {
  const ago = daysBetween(iso.slice(0, 10), today);
  if (ago <= 1) return iso.length > 10 ? iso.slice(11, 16) : "";
  if (ago < 14) return new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" }).format(new Date(iso));
  return shortDate(iso);
}
