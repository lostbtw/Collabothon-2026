import { useMemo, useState, type MouseEvent } from "react";
import type { Forecast } from "../api/types.gen";
import { shortDate } from "../lib/dates";
import { formatMoney } from "../lib/money";
import { chartModel, pointAt, type ChartPoint } from "../pages/dashboard/model";

const compact = new Intl.NumberFormat("en", { notation: "compact" });

/**
 * The cash forecast as one step line: red zone where the balance is below zero, the lowest point
 * labelled, a hover readout. `flash` pulses the low point after a live update.
 */
export function ForecastChart({ forecast, flash }: { forecast: Forecast; flash?: boolean }) {
  const m = useMemo(() => chartModel(forecast), [forecast]);
  const [hover, setHover] = useState<ChartPoint | null>(null);

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * m.w;
    setHover(px < m.plot.left || px > m.plot.right ? null : pointAt(m, px));
  }

  const lowLabel = `${formatMoney(m.low.balance, { decimals: false })} · ${shortDate(m.low.date)}`;
  const lowAnchor = m.low.x > m.w - 90 ? "end" : m.low.x < m.plot.left + 90 ? "start" : "middle";
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${m.w} ${m.h}`} role="img" aria-label={`Cash forecast for ${forecast.horizon_days} days. Lowest point ${lowLabel}.`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
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
        {m.xTicks.map((t) => <text key={t.date} x={t.x} y={m.h - 8} textAnchor="middle" className="chart-tick">{shortDate(t.date)}</text>)}
        {m.band && <path d={m.band} className="chart-band" />}
        <path d={m.line} className="chart-line" />
        {hover && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={m.plot.top} y2={m.plot.bottom} className="chart-cross" />
            <circle cx={hover.x} cy={hover.y} r={4} className="chart-dot" />
          </g>
        )}
        <circle cx={m.low.x} cy={m.low.y} r={5} className={`chart-low${flash ? " flash" : ""}`} />
        <text x={m.low.x} y={m.low.y + 20} textAnchor={lowAnchor} className="chart-low-label">{lowLabel}</text>
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${(hover.x / m.w) * 100}%` }}>
          <div className="caption muted">from {shortDate(hover.date)}</div>
          <div className="medium">{formatMoney(hover.balance, { decimals: false })}</div>
        </div>
      )}
    </div>
  );
}
