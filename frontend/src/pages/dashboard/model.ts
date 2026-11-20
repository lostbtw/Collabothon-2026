// Dashboard logic with no React in it. Geometry may use floating point (it is pixels);
// every number shown to the owner is formatted from the engine's decimal strings.
import type { Forecast, Money } from "../../api/types.gen";
import { daysBetween } from "../../lib/dates";
import { isNegative } from "../../lib/money";

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
export type ChartModel = {
  w: number; h: number; plot: { left: number; right: number; top: number; bottom: number };
  points: ChartPoint[];
  /** Step line: cash stays flat until the next booked day. */
  line: string;
  band: string | null;
  zones: { from: string; to: string; x1: number; x2: number }[];
  low: ChartPoint;
  zeroY: number | null;
  yTicks: { value: number; y: number }[];
  xTicks: { date: string; x: number }[];
};

export function chartModel(f: Forecast, w = 1100, h = 280): ChartModel {
  const plot = { left: 52, right: w - 16, top: 28, bottom: h - 28 };
  const last = f.points.at(-1)?.date ?? f.as_of_date;
  const end = addDays(f.as_of_date, Math.max(f.horizon_days, daysBetween(f.as_of_date, last)));
  const span = Math.max(1, daysBetween(f.as_of_date, end));
  const x = (date: string) => plot.left + (Math.min(span, Math.max(0, daysBetween(f.as_of_date, date))) / span) * (plot.right - plot.left);

  const values = f.points.flatMap((p) => [p.balance, p.low, p.high]).filter((v): v is string => typeof v === "string").map(Number).concat(0);
  const pad = (Math.max(...values) - Math.min(...values)) * 0.12 || 1;
  const lo = Math.min(...values) - pad;
  const hi = Math.max(...values) + pad;
  const y = (v: number) => plot.top + (1 - (v - lo) / (hi - lo)) * (plot.bottom - plot.top);

  const points: ChartPoint[] = f.points.map((p) => ({ date: p.date, balance: { amount: p.balance, currency: f.base_currency }, x: x(p.date), y: y(Number(p.balance)) }));
  const r = (n: number) => Math.round(n * 10) / 10;
  const step = (ys: number[]) => points.map((p, i) => (i === 0 ? `M${r(p.x)} ${r(ys[i])}` : `H${r(p.x)}V${r(ys[i])}`)).join("") + `H${r(plot.right)}`;
  const line = points.length ? step(points.map((p) => p.y)) : "";

  const hasBand = f.points.length > 0 && f.points.every((p) => typeof p.low === "string" && typeof p.high === "string");
  // Upper edge left to right, then the lower edge back right to left.
  const lows = f.points.map((p) => y(Number(p.low)));
  let band: string | null = null;
  if (hasBand) {
    band = `${step(f.points.map((p) => y(Number(p.high))))}V${r(lows.at(-1)!)}`;
    for (let i = points.length - 1; i >= 1; i--) band += `H${r(points[i].x)}V${r(lows[i - 1])}`;
    band += `H${r(points[0].x)}Z`;
  }

  const zones = f.alerts.filter((a) => a.type === "cash_gap").map((a) => ({ from: a.date_from, to: a.date_to ?? end, x1: x(a.date_from), x2: x(a.date_to ?? end) }));
  const low: ChartPoint = { date: f.min_balance.date, balance: f.min_balance.amount, x: x(f.min_balance.date), y: y(Number(f.min_balance.amount.amount)) };

  const tick = niceStep(hi - lo, 4);
  const yTicks: ChartModel["yTicks"] = [];
  for (let v = Math.ceil(lo / tick) * tick; v <= hi; v += tick) if (v !== 0) yTicks.push({ value: v, y: y(v) });
  const every = span > 60 ? 14 : 7;
  const xTicks: ChartModel["xTicks"] = [];
  for (let d = 0; d <= span; d += every) xTicks.push({ date: addDays(f.as_of_date, d), x: x(addDays(f.as_of_date, d)) });

  return { w, h, plot, points, line, band, zones, low, zeroY: lo < 0 && hi > 0 ? y(0) : null, yTicks, xTicks };
}

/** The point whose balance holds at horizontal position `px` (the last booked day at or before it). */
export function pointAt(m: ChartModel, px: number): ChartPoint | null {
  let hit: ChartPoint | null = null;
  for (const p of m.points) if (p.x <= px + 0.5) hit = p;
  return hit ?? m.points[0] ?? null;
}
