import { useMemo, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { BalanceHistory } from "../api/client";
import type { Forecast } from "../api/types.gen";
import { cashDayAt, cashModel, type CashDay } from "../lib/cashChart";
import { shortDate } from "../lib/dates";
import { whole } from "../lib/words";

const compact = new Intl.NumberFormat("en", { notation: "compact" });

/**
 * Cash over time: the solid line is what was in the bank, the dashed line what the forecast expects.
 * Red where the balance would be below zero, the lowest point labelled, a per-day readout on hover.
 * `flash` pulses the lowest point after a live update.
 */
export function CashChart({ history, forecast, flash }: { history: BalanceHistory | null; forecast: Forecast | null; flash?: boolean }) {
  const m = useMemo(() => cashModel(history, forecast), [history, forecast]);
  const [hover, setHover] = useState<CashDay | null>(null);
  const navigate = useNavigate();
  if (!m) return <p className="t2">No balance data yet.</p>;
  // A day with an expected payment opens the rows behind it (the invoice, the bank lines of a series).
  const target = hover?.events.find((e) => e.url)?.url ?? null;
  const open = () => { if (target) navigate(target.replace(/^https?:\/\/[^/]+/, "")); };

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * m!.w;
    setHover(px < m!.plot.left - 8 || px > m!.plot.right + 8 ? null : cashDayAt(m!, px));
  }
  const lowLabel = m.low ? `${whole(m.low.amount)} · ${shortDate(m.low.date)}` : "";
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${m.w} ${m.h}`} role="img" onClick={open} style={{ cursor: target ? "pointer" : undefined }} aria-label={m.low ? `Cash over time. Lowest expected point ${lowLabel}.` : "Cash over time."} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {m.zones.map((z) => (
          <g key={z.from}>
            <rect x={z.x1} y={m.plot.top} width={Math.max(2, z.x2 - z.x1)} height={m.plot.bottom - m.plot.top} className="chart-zone" />
            <text x={(z.x1 + z.x2) / 2} y={m.plot.top + 14} textAnchor="middle" className="chart-label bad-fill">Below zero</text>
          </g>
        ))}
        {m.yTicks.map((t) => (
          <g key={t.value}>
            <line x1={m.plot.left} x2={m.plot.right} y1={t.y} y2={t.y} className="chart-grid" />
            <text x={m.plot.left - 10} y={t.y + 4} textAnchor="end" className="chart-tick">{compact.format(t.value).toLowerCase()}</text>
          </g>
        ))}
        {m.zeroY !== null && (
          <g>
            <line x1={m.plot.left} x2={m.plot.right} y1={m.zeroY} y2={m.zeroY} className="chart-zero" />
            <text x={m.plot.left - 10} y={m.zeroY + 4} textAnchor="end" className="chart-tick">0</text>
          </g>
        )}
        {m.months.map((t) => <text key={t.label + t.x} x={t.x} y={m.h - 8} textAnchor="middle" className="chart-tick">{t.label}</text>)}
        {m.todayX !== null && (
          <g>
            <line x1={m.todayX} x2={m.todayX} y1={m.plot.top - 14} y2={m.plot.bottom} className="chart-today" />
            <text x={m.todayX + 6} y={m.plot.top - 4} className="chart-tick">Today</text>
          </g>
        )}
        {m.band && <path d={m.band} className="chart-band" />}
        {m.past && <path d={m.past} className="chart-line" />}
        {m.future && <path d={m.future} className="chart-line expected" />}
        {hover && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={m.plot.top} y2={m.plot.bottom} className="chart-cross" />
            <circle cx={hover.x} cy={hover.y} r={4} className="chart-dot" />
          </g>
        )}
        {m.low && (
          <>
            <circle cx={m.low.x} cy={m.low.y} r={5} className={`chart-low${flash ? " flash" : ""}`} />
            <text x={m.low.x} y={m.low.y + 20} textAnchor={m.low.x > m.w - 90 ? "end" : "middle"} className="chart-label bad-fill">{lowLabel}</text>
          </>
        )}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${Math.min(86, Math.max(14, (hover.x / m.w) * 100))}%` }}>
          <div className="caption t3">{shortDate(hover.date)} · {hover.expected ? "expected" : "in the bank"}</div>
          <div className="medium">{whole(hover.balance)}</div>
          {hover.low && hover.high && <div className="caption t3">could be {whole(hover.low)} to {whole(hover.high)}</div>}
          {hover.events.map((ev) => <div key={ev.id} className="caption">{ev.label}: {whole(ev.amount)}{ev.source ? <span className="t3"> · from {ev.source}</span> : null}</div>)}
          {target && <div className="caption accent">Click to open</div>}
        </div>
      )}
    </div>
  );
}
