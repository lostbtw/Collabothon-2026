import { useEffect, useState } from "react";
import { api } from "../api/client";

// "Now" for the app: the API's clock (health.demo_clock), which differs from the laptop's when the data is from another day.
let offsetMs: number | null = null;
let asked: Promise<void> | null = null;

function loadOffset(): Promise<void> {
  asked ??= api.health().then((h) => { offsetMs = Date.parse(h.demo_clock) - Date.now(); }).catch(() => { offsetMs = 0; });
  return asked;
}

/** The API's current time in ms, refreshed every `intervalMs`. Null until the clock is known. */
export function useNow(intervalMs = 1000): number | null {
  const [now, setNow] = useState<number | null>(offsetMs === null ? null : Date.now() + offsetMs);
  useEffect(() => {
    let alive = true;
    const tick = () => alive && offsetMs !== null && setNow(Date.now() + offsetMs);
    void loadOffset().then(tick);
    const timer = setInterval(tick, intervalMs);
    return () => { alive = false; clearInterval(timer); };
  }, [intervalMs]);
  return now;
}

/** "8 s ago", "3 min ago", "2 h ago", "4 days ago". */
export function ago(iso: string, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86_400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}
