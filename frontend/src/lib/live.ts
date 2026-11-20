import { useEffect, useRef } from "react";
import { subscribeEvents } from "../api/client";
import { API_MODE } from "../config";
import type { OrdoEvent } from "../api/types.gen";
import { useCompany } from "./company";

// One event stream for the whole app; screens listen to it instead of each opening their own.
type Listener = (e: OrdoEvent) => void;
const listeners = new Set<Listener>();
let stop: (() => void) | null = null;
let streamFor: string | null = null;

/** Mock mode replays the sample events once per browser tab; add ?replay=1 to the URL to see them again. */
function mockAlreadyReplayed(): boolean {
  if (API_MODE !== "mock" || typeof window === "undefined") return false;
  try {
    if (new URLSearchParams(window.location.search).get("replay") === "1") return false;
    if (window.sessionStorage.getItem("ordo.replayed")) return true;
    window.sessionStorage.setItem("ordo.replayed", "1");
  } catch {
    // No sessionStorage: replay every time.
  }
  return false;
}

function connect(companyId: string): void {
  if (stop && streamFor === companyId) return;
  if (!stop && mockAlreadyReplayed()) { stop = () => {}; streamFor = companyId; return; }
  stop?.();
  streamFor = companyId;
  stop = subscribeEvents((e) => listeners.forEach((l) => l(e)), companyId);
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
