// The switch between mock data (default, from contracts/fixtures) and the live API: VITE_API_MODE=live, or ?mock=0 / ?mock=1.
export type ApiMode = "mock" | "live";

function readMode(): ApiMode {
  const fromEnv: ApiMode = import.meta.env?.VITE_API_MODE === "live" ? "live" : "mock";
  if (typeof window === "undefined") return fromEnv;
  try {
    const flag = new URLSearchParams(window.location.search).get("mock");
    if (flag === "0" || flag === "1") window.sessionStorage.setItem("ordo.mock", flag);
    const stored = window.sessionStorage.getItem("ordo.mock");
    if (stored === "0") return "live";
    if (stored === "1") return "mock";
  } catch {
    // sessionStorage can be unavailable (private mode); fall back to the build-time value.
  }
  return fromEnv;
}

export const API_MODE: ApiMode = readMode();
export const API_BASE: string = import.meta.env?.VITE_API_BASE ?? "/api/v1";
export const DEFAULT_COMPANY_ID = "co_borsuk";
