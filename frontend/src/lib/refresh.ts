import { useEffect, useState } from "react";
import { clearCache } from "../api/transport";

// A page that changes shared data (for example a decision in the inbox) calls requestRefresh();
// the shell re-reads its counters. No data is passed around: everyone re-asks the API.
const listeners = new Set<() => void>();

export function requestRefresh(): void {
  clearCache(); // re-ask the API, not the short-lived cache
  listeners.forEach((listener) => listener());
}

/** A number that changes on every requestRefresh(); put it in a useApi dependency list. */
export function useRefreshKey(): number {
  const [key, setKey] = useState(0);
  useEffect(() => {
    const listener = () => setKey((k) => k + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return key;
}
