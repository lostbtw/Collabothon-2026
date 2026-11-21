// Dashboard logic with no React in it; pixels may be floats, every number shown comes from the engine's decimal strings.
import type { EvidenceLink, Forecast, Money, Transaction } from "../../api/types.gen";
import { daysBetween } from "../../lib/dates";
import { isNegative } from "../../lib/money";

export type DataNote = { text: string; evidence: EvidenceLink };

/** Plain notes about data Ordo had to repair, each with the row that shows it. Built from the bank lines' quality flags. */
export function dataNotes(transactions: Transaction[]): DataNote[] {
  const notes: DataNote[] = [];
  const converted = transactions.filter((t) => t.data_quality?.includes("currency_mismatch_fixed"));
  if (converted.length > 0) {
    const t = converted[0];
    const from = t.original_amount?.currency ?? t.amount.currency;
    notes.push({
      text: `${converted.length} ${from} line${converted.length === 1 ? "" : "s"} converted to ${t.amount_base.currency}`,
      evidence: { kind: "transaction", id: t.id, label: t.fx ? `Rate ${t.fx.rate}, from ${t.fx.source}` : "Open the line", url: `/transactions/${t.id}` },
    });
  }
  const unresolved = transactions.filter((t) => t.data_quality?.includes("counterparty_unresolved"));
  if (unresolved.length > 0) notes.push({ text: `${unresolved.length} line${unresolved.length === 1 ? "" : "s"} with an unknown counterparty`, evidence: { kind: "transaction", id: unresolved[0].id, label: "Open the first one", url: `/transactions/${unresolved[0].id}` } });
  return notes;
}

export type Weather = { kind: "storm" | "cloudy" | "sunny"; headline: string };

/** Cash weather: storm = the balance goes below zero, cloudy = it dips under the safety buffer, sunny otherwise. */
export function weather(f: Forecast): Weather {
  const inDays = (date: string) => {
    const n = daysBetween(f.as_of_date, date);
    return n <= 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`;
  };
  if (f.first_negative_date) return { kind: "storm", headline: `Cash gap ${inDays(f.first_negative_date)}` };
  const underBuffer = f.safety_buffer && Number(f.min_balance.amount.amount) < Number(f.safety_buffer.amount);
  if (underBuffer || isNegative(f.min_balance.amount)) return { kind: "cloudy", headline: `Thin cushion ${inDays(f.min_balance.date)}` };
  return { kind: "sunny", headline: `No gap in the next ${f.horizon_days} days` };
}

const addDays = (date: string, n: number): string => new Date(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)) + n)).toISOString().slice(0, 10);

function niceStep(range: number, target: number): number {
  const raw = range / target;
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
}

export type ChartPoint = { date: string; balance: Money; x: number; y: number };

/** One dated thing the forecast expects: a payment in or out, with how sure the engine is and where it comes from. */
export type Upcoming = { id: string; date: string; label: string; amount: Money; confidence: number; source: string; url?: string };

/** Everything the forecast expects, by date. The opening balance is not an event and is left out. */
export function upcoming(f: Forecast): Upcoming[] {
  return f.components
    .filter((c) => c.kind !== "opening_balance")
    .flatMap((c) => (c.dates ?? []).map((date) => ({
      id: `${c.id}@${date}`, date, label: c.label, amount: c.amount_base, confidence: c.confidence,
      source: (c.evidence ?? []).map((e) => e.label).join(", "), url: c.evidence?.find((e) => e.url)?.url,
    })))
    .sort((a, b) => a.date.localeCompare(b.date));
}

/** The balance on every single day of the forecast: it holds from one booked day until the next. */
export function dailyBalances(f: Forecast, days: number = Math.max(f.horizon_days, daysBetween(f.as_of_date, f.points.at(-1)?.date ?? f.as_of_date))): { date: string; balance: Money }[] {
  const out: { date: string; balance: Money }[] = [];
  let current = f.points[0]?.balance ?? f.opening_balance.amount;
  let next = 0;
  for (let d = 0; d <= days; d++) {
    const date = addDays(f.as_of_date, d);
    while (next < f.points.length && f.points[next].date <= date) current = f.points[next++].balance;
    out.push({ date, balance: { amount: current, currency: f.base_currency } });
  }
  return out;
}

export type ChartOptions = { w?: number; h?: number; days?: number; buffer?: boolean };
export type ChartModel = {
  w: number; h: number; plot: { left: number; right: number; top: number; bottom: number };
  points: ChartPoint[];
  /** Step line: cash stays flat until the next booked day. */
  line: string;
  band: string | null;
  zones: { from: string; to: string; x1: number; x2: number }[];
  low: ChartPoint;
  /** False when the lowest point is outside the chosen range. */
  lowVisible: boolean;
  /** Expected payments in range, placed on the line at their date. */
  events: (Upcoming & { x: number; y: number })[];
  bufferY: number | null;
  zeroY: number | null;
  yTicks: { value: number; y: number }[];
  /** One tick per day (per week on very long ranges); `month` is set where a month starts. */
  xTicks: { date: string; x: number; day: number; month: string | null }[];
  /** Every day in range with its balance, for the hover readout. */
  days: ChartPoint[];
};

const monthName = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });

export function chartModel(f: Forecast, { w = 1100, h = 300, days, buffer = false }: ChartOptions = {}): ChartModel {
  const plot = { left: 52, right: w - 16, top: 28, bottom: h - 44 };
  const last = f.points.at(-1)?.date ?? f.as_of_date;
  const full = Math.max(f.horizon_days, daysBetween(f.as_of_date, last));
  const span = Math.max(1, Math.min(days ?? full, full));
  const end = addDays(f.as_of_date, span);
  const inRange = (date: string) => date >= f.as_of_date && date <= end;
  const visible = f.points.filter((p) => inRange(p.date));
  const bufferValue = buffer && f.safety_buffer ? Number(f.safety_buffer.amount) : null;
  const x = (date: string) => plot.left + (Math.min(span, Math.max(0, daysBetween(f.as_of_date, date))) / span) * (plot.right - plot.left);

  const values = visible.flatMap((p) => [p.balance, p.low, p.high]).filter((v): v is string => typeof v === "string").map(Number).concat(0, bufferValue ?? 0);
  const pad = (Math.max(...values) - Math.min(...values)) * 0.12 || 1;
  const lo = Math.min(...values) - pad;
  const hi = Math.max(...values) + pad;
  const y = (v: number) => plot.top + (1 - (v - lo) / (hi - lo)) * (plot.bottom - plot.top);

  const points: ChartPoint[] = visible.map((p) => ({ date: p.date, balance: { amount: p.balance, currency: f.base_currency }, x: x(p.date), y: y(Number(p.balance)) }));
  const r = (n: number) => Math.round(n * 10) / 10;
  const step = (ys: number[]) => points.map((p, i) => (i === 0 ? `M${r(p.x)} ${r(ys[i])}` : `H${r(p.x)}V${r(ys[i])}`)).join("") + `H${r(plot.right)}`;
  const line = points.length ? step(points.map((p) => p.y)) : "";

  const hasBand = visible.length > 0 && visible.every((p) => typeof p.low === "string" && typeof p.high === "string");
  // Upper edge left to right, then the lower edge back right to left.
  const lows = visible.map((p) => y(Number(p.low)));
  let band: string | null = null;
  if (hasBand) {
    band = `${step(visible.map((p) => y(Number(p.high))))}V${r(lows.at(-1)!)}`;
    for (let i = points.length - 1; i >= 1; i--) band += `H${r(points[i].x)}V${r(lows[i - 1])}`;
    band += `H${r(points[0].x)}Z`;
  }

  const zones = f.alerts.filter((a) => a.type === "cash_gap" && a.date_from <= end).map((a) => ({ from: a.date_from, to: a.date_to ?? end, x1: x(a.date_from), x2: x(a.date_to ?? end) }));
  // An expected payment sits on the line at the balance that holds on its date.
  const balanceY = (date: string) => { let hit = points[0]; for (const p of points) if (p.date <= date) hit = p; return hit?.y ?? plot.bottom; };
  const events = upcoming(f).filter((u) => inRange(u.date)).map((u) => ({ ...u, x: x(u.date), y: balanceY(u.date) }));
  const low: ChartPoint = { date: f.min_balance.date, balance: f.min_balance.amount, x: x(f.min_balance.date), y: y(Number(f.min_balance.amount.amount)) };

  const tick = niceStep(hi - lo, 4);
  const yTicks: ChartModel["yTicks"] = [];
  for (let v = Math.ceil(lo / tick) * tick; v <= hi; v += tick) if (v !== 0) yTicks.push({ value: v, y: y(v) });
  const every = span > 62 ? 7 : 1;
  const xTicks: ChartModel["xTicks"] = [];
  for (let d = 0; d <= span; d += every) {
    const date = addDays(f.as_of_date, d);
    const day = Number(date.slice(8, 10));
    xTicks.push({ date, x: x(date), day, month: d === 0 || day === 1 || (every > 1 && day <= every) ? monthName.format(new Date(`${date}T12:00:00Z`)) : null });
  }
  const daily = dailyBalances(f, span).map((d) => ({ ...d, x: x(d.date), y: y(Number(d.balance.amount)) }));

  return {
    w, h, plot, points, line, band, zones, low, lowVisible: inRange(f.min_balance.date), events,
    bufferY: bufferValue === null ? null : y(bufferValue), zeroY: lo < 0 && hi > 0 ? y(0) : null, yTicks, xTicks, days: daily,
  };
}

/** The day under horizontal position `px`, with the balance on that day. */
export function dayAt(m: ChartModel, px: number): ChartPoint | null {
  if (m.days.length === 0) return null;
  const step = m.days.length > 1 ? m.days[1].x - m.days[0].x : 1;
  return m.days[Math.min(m.days.length - 1, Math.max(0, Math.round((px - m.plot.left) / step)))];
}

/** The point whose balance holds at horizontal position `px` (the last booked day at or before it). */
export function pointAt(m: ChartModel, px: number): ChartPoint | null {
  let hit: ChartPoint | null = null;
  for (const p of m.points) if (p.x <= px + 0.5) hit = p;
  return hit ?? m.points[0] ?? null;
}
