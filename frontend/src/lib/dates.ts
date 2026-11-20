// Date helpers. The API sends ISO strings; a date without a time ("2026-11-30") is a calendar day
// and must not shift with the viewer's time zone.
//
// Times are shown in ONE zone for everyone, set here. The demo data is written in UTC, so UTC keeps
// the story's clock times and deadlines ("by 27 Nov") the same on every laptop.
export const DISPLAY_TIME_ZONE = "UTC";

const isDay = (iso: string) => /^\d{4}-\d{2}-\d{2}$/.test(iso);
const toDate = (iso: string) => new Date(isDay(iso) ? `${iso}T12:00:00Z` : iso);

// Newer ICU writes September as "Sept" in en-GB; every other short month has three letters.
const sep = (s: string) => s.replace("Sept", "Sep");

/** "27 Nov" */
export function shortDate(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: isDay(iso) ? "UTC" : timeZone }).format(toDate(iso)));
}

/** "15 May 2025" */
export function longDate(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: isDay(iso) ? "UTC" : timeZone }).format(toDate(iso)));
}

/** "21 Nov, 10:15" */
export function dateTime(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone }).format(toDate(iso)));
}

/** Whole calendar days from `from` to `to` (both taken as calendar days). */
export function daysBetween(from: string, to: string): number {
  const day = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
  return Math.round((day(to) - day(from)) / 86_400_000);
}
