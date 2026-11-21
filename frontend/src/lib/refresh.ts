import { useEffect, useState } from "react";
import { clearCache } from "../api/transport";

// A page that changes shared data calls requestRefresh(); the shell re-asks the API for its counters.
const listeners = new Set<() => void>();

export function requestRefresh(): void {
  clearCache();
  listeners.forEach((listener) => listener());
}

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
