// Date helpers: a date without a time is a calendar day, and times show in UTC (the demo data's zone) on every laptop.
export const DISPLAY_TIME_ZONE = "UTC";

const isDay = (iso: string) => /^\d{4}-\d{2}-\d{2}$/.test(iso);
const toDate = (iso: string) => new Date(isDay(iso) ? `${iso}T12:00:00Z` : iso);

// Newer ICU writes September as "Sept" in en-GB; every other short month has three letters.
const sep = (s: string) => s.replace("Sept", "Sep");

export function shortDate(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: isDay(iso) ? "UTC" : timeZone }).format(toDate(iso)));
}

export function longDate(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: isDay(iso) ? "UTC" : timeZone }).format(toDate(iso)));
}

export function dateTime(iso: string, timeZone: string = DISPLAY_TIME_ZONE): string {
  return sep(new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone }).format(toDate(iso)));
}

export function daysBetween(from: string, to: string): number {
  const day = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
  return Math.round((day(to) - day(from)) / 86_400_000);
}
