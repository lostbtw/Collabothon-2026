import { useEffect, useRef } from "react";
import { subscribeEvents } from "../api/client";
import type { OrdoEvent } from "../api/types.gen";
import { useCompany } from "./company";

// One event stream for the whole app; screens listen to it instead of each opening their own.
type Listener = (e: OrdoEvent) => void;
const listeners = new Set<Listener>();
let stop: (() => void) | null = null;
let streamFor: string | null = null;

function connect(companyId: string): void {
  if (stop && streamFor === companyId) return;
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
