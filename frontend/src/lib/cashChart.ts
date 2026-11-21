// Geometry of "Cash over time": pixels may be floats; every number shown is formatted from the backend's decimal strings.
import type { BalanceHistory } from "../api/client";
import type { Forecast, Money } from "../api/types.gen";
import { dailyBalances, upcoming, type Upcoming } from "../pages/dashboard/model";
import { daysBetween } from "./dates";

export const addDays = (date: string, n: number): string =>
  new Date(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)) + n)).toISOString().slice(0, 10);

function niceStep(range: number, target: number): number {
  const raw = range / target;
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
}

export type CashDay = { date: string; balance: Money; expected: boolean; x: number; y: number; events: Upcoming[]; low?: Money; high?: Money };
export type CashModel = {
  w: number; h: number; plot: { left: number; right: number; top: number; bottom: number };
  past: string | null; future: string | null; todayX: number | null;
  band: string | null;
  zones: { from: string; to: string; x1: number; x2: number }[];
  low: { date: string; amount: Money; x: number; y: number } | null;
  zeroY: number | null; yTicks: { value: number; y: number }[]; months: { x: number; label: string }[];
  days: CashDay[];
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function cashModel(history: BalanceHistory | null, forecast: Forecast | null, { w = 1000, h = 260 } = {}): CashModel | null {
  const pastPoints = (history?.points ?? []).filter((p) => !forecast || p.date < forecast.as_of_date);
  if (!forecast && pastPoints.length === 0) return null;
  const today = forecast?.as_of_date ?? addDays(pastPoints[pastPoints.length - 1].date, 1);
  const start = pastPoints[0]?.date ?? today;
  const end = forecast ? addDays(today, Math.max(forecast.horizon_days, daysBetween(today, forecast.points.at(-1)?.date ?? today))) : today;
  const span = Math.max(1, daysBetween(start, end));
  const currency = forecast?.base_currency ?? history?.currency ?? "";
  const plot = { left: 52, right: w - 12, top: 30, bottom: h - 34 };
  const x = (date: string) => plot.left + (Math.min(span, Math.max(0, daysBetween(start, date))) / span) * (plot.right - plot.left);

  const days: Omit<CashDay, "x" | "y">[] = [];
  let held = pastPoints[0]?.balance;
  let next = 0;
  for (let d = start; d < today; d = addDays(d, 1)) {
    while (next < pastPoints.length && pastPoints[next].date <= d) held = pastPoints[next++].balance;
    if (held !== undefined) days.push({ date: d, balance: { amount: held, currency }, expected: false, events: [] });
  }
  const events = forecast ? upcoming(forecast) : [];
  if (forecast) for (const b of dailyBalances(forecast, daysBetween(today, end))) days.push({ ...b, expected: true, events: events.filter((e) => e.date === b.date) });

  const ranged = (forecast?.points ?? []).filter((p) => p.date >= today && p.date <= end && typeof p.low === "string" && typeof p.high === "string");
  const values = days.map((d) => Number(d.balance.amount)).concat(0, ...ranged.flatMap((p) => [Number(p.low), Number(p.high)]));
  const pad = (Math.max(...values) - Math.min(...values)) * 0.08 || 1;
  const lo = Math.min(...values) - pad;
  const hi = Math.max(...values) + pad;
  const y = (v: number) => plot.top + (1 - (v - lo) / (hi - lo)) * (plot.bottom - plot.top);
  const r = (n: number) => Math.round(n * 10) / 10;

  const step = (pts: { date: string; v: number }[], endX: number) =>
    pts.map((p, i) => (i === 0 ? `M${r(x(p.date))} ${r(y(p.v))}` : `H${r(x(p.date))}V${r(y(p.v))}`)).join("") + `H${r(endX)}`;
  const past = pastPoints.length ? step(pastPoints.map((p) => ({ date: p.date, v: Number(p.balance) })), x(today)) : null;
  const futurePoints = forecast ? forecast.points.filter((p) => p.date >= today && p.date <= end).map((p) => ({ date: p.date, v: Number(p.balance) })) : [];
  const lastPast = pastPoints.at(-1);
  const joined = lastPast && futurePoints.length && futurePoints[0].date > today ? [{ date: today, v: Number(lastPast.balance) }, ...futurePoints] : futurePoints;
  const future = joined.length ? step(joined, plot.right) : null;

  let band: string | null = null;
  if (ranged.length > 1) {
    const top = ranged.map((p, i) => (i === 0 ? `M${r(x(p.date))} ${r(y(Number(p.high)))}` : `H${r(x(p.date))}V${r(y(Number(p.high)))}`)).join("") + `H${r(plot.right)}`;
    let bottom = `V${r(y(Number(ranged[ranged.length - 1].low)))}`;
    for (let i = ranged.length - 1; i >= 1; i--) bottom += `H${r(x(ranged[i].date))}V${r(y(Number(ranged[i - 1].low)))}`;
    band = `${top}${bottom}H${r(x(ranged[0].date))}Z`;
  }
  const lowHigh = new Map(ranged.map((p) => [p.date, p]));

  const zones = (forecast?.alerts ?? []).filter((a) => a.type === "cash_gap" && a.date_from <= end)
    .map((a) => ({ from: a.date_from, to: a.date_to ?? end, x1: x(a.date_from), x2: x(a.date_to ?? end) }));
  const low = forecast && forecast.min_balance.date <= end
    ? { date: forecast.min_balance.date, amount: forecast.min_balance.amount, x: x(forecast.min_balance.date), y: y(Number(forecast.min_balance.amount.amount)) } : null;

  const tick = niceStep(hi - lo, 4);
  const yTicks: CashModel["yTicks"] = [];
  for (let v = Math.ceil(lo / tick) * tick; v <= hi; v += tick) if (Math.abs(v) > tick / 1000) yTicks.push({ value: v, y: y(v) });
  const months: CashModel["months"] = [];
  for (let d = `${start.slice(0, 7)}-01`; d <= end; d = addDays(d, 32).slice(0, 7) + "-01") if (d > start) months.push({ x: x(d), label: MONTHS[Number(d.slice(5, 7)) - 1] });

  return {
    w, h, plot, past, future, band, todayX: forecast ? x(today) : null, zones, low, zeroY: lo < 0 && hi > 0 ? y(0) : null, yTicks, months,
    days: days.map((d) => {
      const known = [...lowHigh.keys()].filter((k) => k <= d.date).pop();
      const p = d.expected && known ? lowHigh.get(known) : undefined;
      return { ...d, x: x(d.date), y: y(Number(d.balance.amount)), ...(p ? { low: { amount: p.low!, currency }, high: { amount: p.high!, currency } } : {}) };
    }),
  };
}

export function cashDayAt(m: CashModel, px: number): CashDay | null {
  if (m.days.length === 0) return null;
  let best = m.days[0];
  for (const d of m.days) if (Math.abs(d.x - px) < Math.abs(best.x - px)) best = d;
  return best;
}
