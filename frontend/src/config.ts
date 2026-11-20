// THE switch between mock data and the real API.
//
//   mock (default): every API call is answered from contracts/fixtures.
//   live:           every API call goes to API_BASE (the skeleton API, later the real one).
//
// Change it in one of two ways, nothing else in the app needs to change:
//   1. Build/run time:  VITE_API_MODE=live npm run dev
//   2. In the browser:  add ?mock=0 (live) or ?mock=1 (mock) to any URL; remembered for the tab.
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
