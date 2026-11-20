import { useMemo, useState, type MouseEvent } from "react";
import type { Forecast } from "../api/types.gen";
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { chartModel, dayAt, type ChartPoint } from "../pages/dashboard/model";

const compact = new Intl.NumberFormat("en", { notation: "compact" });

export type ChartView = { days: number; events: boolean; buffer: boolean };

/**
 * The cash forecast as one step line: red zone where the balance is below zero, the lowest point
 * labelled, one tick per day, a per-day hover readout that also names what is paid on that day. `view` is the owner's choice of
 * range and extras; `flash` pulses the low point after a live update.
 */
export function ForecastChart({ forecast, flash, view }: { forecast: Forecast; flash?: boolean; view?: Partial<ChartView> }) {
  const m = useMemo(() => chartModel(forecast, { days: view?.days, buffer: view?.buffer }), [forecast, view?.days, view?.buffer]);
  const [hover, setHover] = useState<ChartPoint | null>(null);
  const showEvents = view?.events ?? true;

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * m.w;
    setHover(px < m.plot.left - 8 || px > m.plot.right + 8 ? null : dayAt(m, px));
  }

  const lowLabel = `${formatMoney(m.low.balance, { decimals: false })} · ${shortDate(m.low.date)}`;
  const lowAnchor = m.low.x > m.w - 90 ? "end" : m.low.x < m.plot.left + 90 ? "start" : "middle";
  const onHoverDay = hover ? m.events.filter((ev) => ev.date === hover.date) : [];
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${m.w} ${m.h}`} role="img" aria-label={`Cash forecast. Lowest point ${lowLabel}.`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {m.zones.map((z) => (
          <g key={z.from}>
            <rect x={z.x1} y={m.plot.top} width={Math.max(2, z.x2 - z.x1)} height={m.plot.bottom - m.plot.top} className="chart-zone" />
            <text x={z.x1 + 6} y={m.plot.top - 8} className="chart-zone-label">Below zero {shortDate(z.from)} – {shortDate(z.to)}</text>
          </g>
        ))}
        {m.yTicks.map((t) => (
          <g key={t.value}>
            <line x1={m.plot.left} x2={m.plot.right} y1={t.y} y2={t.y} className="chart-grid" />
            <text x={m.plot.left - 8} y={t.y + 4} textAnchor="end" className="chart-tick">{compact.format(t.value)}</text>
          </g>
        ))}
        {m.zeroY !== null && (
          <g>
            <line x1={m.plot.left} x2={m.plot.right} y1={m.zeroY} y2={m.zeroY} className="chart-zero" />
            <text x={m.plot.left - 8} y={m.zeroY + 4} textAnchor="end" className="chart-tick">0</text>
          </g>
        )}
        {m.bufferY !== null && forecast.safety_buffer && (
          <g>
            <line x1={m.plot.left} x2={m.plot.right} y1={m.bufferY} y2={m.bufferY} className="chart-buffer" />
            <text x={m.plot.right} y={m.bufferY - 6} textAnchor="end" className="chart-tick">Safety buffer {formatMoney(forecast.safety_buffer, { decimals: false })}</text>
          </g>
        )}
        {m.xTicks.map((t) => (
          <g key={t.date}>
            <text x={t.x} y={m.plot.bottom + 16} textAnchor="middle" className={`chart-day${hover?.date === t.date ? " on" : ""}`}>{t.day}</text>
            {t.month && <text x={t.x} y={m.plot.bottom + 34} textAnchor="middle" className="chart-month">{t.month}</text>}
          </g>
        ))}
        {m.band && <path d={m.band} className="chart-band" />}
        <path d={m.line} className="chart-line" />
        {showEvents && m.events.map((ev) => <circle key={ev.id} cx={ev.x} cy={ev.y} r={4} className={`chart-event${ev.amount.amount.startsWith("-") ? "" : " in"}`} />)}
        {hover && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={m.plot.top} y2={m.plot.bottom} className="chart-cross" />
            <circle cx={hover.x} cy={hover.y} r={4} className="chart-dot" />
          </g>
        )}
        {m.lowVisible && (
          <>
            <circle cx={m.low.x} cy={m.low.y} r={5} className={`chart-low${flash ? " flash" : ""}`} />
            <text x={m.low.x} y={m.low.y + 20} textAnchor={lowAnchor} className="chart-low-label">{lowLabel}</text>
          </>
        )}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${Math.min(86, Math.max(14, (hover.x / m.w) * 100))}%` }}>
          <div className="caption muted">{shortDate(hover.date)}</div>
          <div className="medium">{formatMoney(hover.balance, { decimals: false })}</div>
          {onHoverDay.map((ev) => <div key={ev.id} className="caption">{ev.label}: {formatMoney(ev.amount, { decimals: false })}</div>)}
        </div>
      )}
    </div>
  );
}
