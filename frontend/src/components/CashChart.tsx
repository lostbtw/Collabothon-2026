import { useMemo, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { BalanceHistory } from "../api/client";
import type { Forecast } from "../api/types.gen";
import { cashDayAt, cashModel, type CashDay } from "../lib/cashChart";
import { add } from "../lib/costTypes";
import { longDate, shortDate } from "../lib/dates";
import { whole } from "../lib/words";
import type { Upcoming } from "../pages/dashboard/model";
import { Modal, ModalSection } from "./Modal";

const compact = new Intl.NumberFormat("en", { notation: "compact" });

/** Cash over time: solid history, dashed forecast, red below zero; hover shows a day, a click opens what is expected on it. */
export function CashChart({ history, forecast, flash }: { history: BalanceHistory | null; forecast: Forecast | null; flash?: boolean }) {
  const m = useMemo(() => cashModel(history, forecast), [history, forecast]);
  const [hover, setHover] = useState<CashDay | null>(null);
  const [day, setDay] = useState<CashDay | null>(null);
  if (!m) return <p className="t2">No balance data yet.</p>;
  const open = () => { if (hover?.expected) setDay(hover); };

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * m!.w;
    setHover(px < m!.plot.left - 8 || px > m!.plot.right + 8 ? null : cashDayAt(m!, px));
  }
  const lowLabel = m.low ? `${whole(m.low.amount)} · ${shortDate(m.low.date)}` : "";
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${m.w} ${m.h}`} role="img" onClick={open} style={{ cursor: hover?.expected ? "pointer" : undefined }} aria-label={m.low ? `Cash over time. Lowest expected point ${lowLabel}.` : "Cash over time."} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
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
          {hover.expected && <div className="caption accent">Click for details</div>}
        </div>
      )}
      {day && <DayModal day={day} onClose={() => setDay(null)} />}
    </div>
  );
}

/** One forecast day: where the balance ends, how far it could be off, and every payment expected that day. */
function DayModal({ day, onClose }: { day: CashDay; onClose: () => void }) {
  const navigate = useNavigate();
  const ins = day.events.filter((e) => !e.amount.amount.startsWith("-"));
  const outs = day.events.filter((e) => e.amount.amount.startsWith("-"));
  const net = day.events.length ? { amount: day.events.reduce((s, e) => add(s, e.amount.amount), "0.00"), currency: day.balance.currency } : null;
  const go = (url: string) => { onClose(); navigate(url.replace(/^https?:\/\/[^/]+/, "")); };
  const list = (title: string, items: Upcoming[]) => items.length > 0 && (
    <ModalSection title={title}>
      <div className="day-list">
        {items.map((e) => (
          <div key={e.id} className="day-row">
            <div className="stack grow" style={{ gap: 2 }}>
              <span className="medium small">{e.label}</span>
              <span className="caption t3">{[e.source && `from ${e.source}`, e.confidence < 1 && `${Math.round(e.confidence * 100)}% sure`].filter(Boolean).join(" · ")}</span>
            </div>
            <span className={`nowrap${e.amount.amount.startsWith("-") ? "" : " good"}`}>{e.amount.amount.startsWith("-") ? "" : "+"}{whole(e.amount)}</span>
            {e.url ? <button type="button" className="quiet" onClick={() => go(e.url!)}>Open</button> : <span className="day-open-gap" />}
          </div>
        ))}
      </div>
    </ModalSection>
  );
  const below = day.balance.amount.startsWith("-");
  return (
    <Modal title={longDate(day.date)} onClose={onClose} head={<span className="status suggestion">Expected</span>}>
      <div className="facts">
        <div className="stack" style={{ gap: 0 }}><span className="small t3">Balance at the end of the day</span><span className={below ? "bad medium" : "medium"}>{whole(day.balance)}</span></div>
        {day.low && day.high && <div className="stack" style={{ gap: 0 }}><span className="small t3">Could be</span><span>{whole(day.low)} to {whole(day.high)}</span></div>}
        {net && <div className="stack" style={{ gap: 0 }}><span className="small t3">Change that day</span><span className={net.amount.startsWith("-") ? undefined : "good"}>{net.amount.startsWith("-") ? "" : "+"}{whole(net)}</span></div>}
      </div>
      {list("Money in", ins)}
      {list("Money out", outs)}
      {day.events.length === 0 && <span className="t2">Nothing is expected to come in or go out on this day.</span>}
    </Modal>
  );
}
