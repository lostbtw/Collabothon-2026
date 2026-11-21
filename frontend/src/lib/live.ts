import { useEffect, useRef } from "react";
import { subscribeEvents } from "../api/client";
import type { OrdoEvent } from "../api/types.gen";
import { useCompany } from "./company";

// One event stream for the whole app; screens listen to it instead of each opening their own.
type Listener = (e: OrdoEvent) => void;
const listeners = new Set<Listener>();
let stop: (() => void) | null = null;
let streamFor: string | null = null;

// The stream replays recent events on connect: each is passed on once per tab, unless the URL has ?replay=1.
const SEEN_KEY = "ordo.seenEvents";
function loadSeen(): Set<string> {
  try {
    if (new URLSearchParams(window.location.search).get("replay") === "1") window.sessionStorage.removeItem(SEEN_KEY);
    return new Set(JSON.parse(window.sessionStorage.getItem(SEEN_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}
const seen = typeof window === "undefined" ? new Set<string>() : loadSeen();

/** True the first time an event id is met in this tab. */
export function isNew(e: OrdoEvent, known: Set<string> = seen): boolean {
  if (known.has(e.id)) return false;
  known.add(e.id);
  if (known === seen) {
    try {
      window.sessionStorage.setItem(SEEN_KEY, JSON.stringify([...known].slice(-500)));
    } catch {
      // No sessionStorage: old events may repeat after a reload.
    }
  }
  return true;
}

function connect(companyId: string): void {
  if (stop && streamFor === companyId) return;
  stop?.();
  streamFor = companyId;
  stop = subscribeEvents((e) => { if (isNew(e)) listeners.forEach((l) => l(e)); }, companyId);
}

/** Calls `onEvent` for every live event of the selected company while the component is on screen. */
export function useLive(onEvent: Listener): void {
  const { companyId } = useCompany();
  const latest = useRef(onEvent);
  latest.current = onEvent;
  useEffect(() => {
    const listener: Listener = (e) => latest.current(e);
    listeners.add(listener);
    connect(companyId);
    return () => { listeners.delete(listener); };
  }, [companyId]);
}
