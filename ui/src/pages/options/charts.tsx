import { useCallback, useId, useRef, useState } from "react";
import type { Payoff } from "../../api/queries";
import { price, qty, rupees } from "../../lib/format";

// The Option chain page's charts (ADR 38): plain SVG, drawn at the width they
// get. Price is their x axis, which lightweight-charts (time only) can't draw.

const PAD = { top: 12, right: 12, bottom: 22, left: 56 };

/** A callback ref and the width of what it's on, kept as it resizes. */
function useWidth<T extends HTMLElement>() {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((element: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!element) return;
    setWidth(element.clientWidth);
    observer.current = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width));
    });
    observer.current.observe(element);
  }, []);
  return [ref, width] as const;
}

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** About `count` round values across [lo, hi]: 24,400 · 24,600 · … */
function ticks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  const step = ([1, 2, 2.5, 5, 10].find((s) => s * power >= raw) ?? 10) * power;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

const short = (v: number) =>
  Math.abs(v) >= 1e5
    ? `${(v / 1e5).toFixed(1)}L`
    : Math.abs(v) >= 1e3
      ? `${(v / 1e3).toFixed(0)}k`
      : v.toFixed(0);

const line = (xs: number[], ys: number[]) =>
  xs.map((x, n) => `${n ? "L" : "M"}${x.toFixed(1)},${(ys[n] as number).toFixed(1)}`).join("");

/**
 * P&L across the underlying: at expiry (solid, green over zero, red under)
 * and today (dashed). Hovering reads both off at that price.
 */
export function PayoffChart({
  payoff,
  spot,
  height = 220,
}: {
  payoff: Payoff;
  spot: number;
  height?: number;
}) {
  const [box, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const clip = useId();
  const points = payoff.points;
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return null;

  const values = points.flatMap((p) => (p.today === null ? [p.at_expiry] : [p.at_expiry, p.today]));
  let lo = Math.min(0, ...values);
  let hi = Math.max(0, ...values);
  const room = (hi - lo) * 0.08 || 1;
  lo -= room;
  hi += room;
  const x = scale(
    [first.underlying, last.underlying],
    [PAD.left, Math.max(width - PAD.right, PAD.left + 1)],
  );
  const y = scale([lo, hi], [height - PAD.bottom, PAD.top]);
  const xs = points.map((p) => x(p.underlying));
  const expiry = line(
    xs,
    points.map((p) => y(p.at_expiry)),
  );
  const today = points.every((p) => p.today !== null)
    ? line(
        xs,
        points.map((p) => y(p.today as number)),
      )
    : null;
  const zero = y(0);
  const area = `${expiry}L${xs[xs.length - 1]},${zero}L${xs[0]},${zero}Z`;
  const shown = hover === null ? null : points[hover];

  const move = (event: React.PointerEvent<SVGSVGElement>) => {
    const left = event.currentTarget.getBoundingClientRect().left;
    const at = event.clientX - left;
    let best = 0;
    for (let n = 1; n < xs.length; n++) {
      if (Math.abs((xs[n] as number) - at) < Math.abs((xs[best] as number) - at)) best = n;
    }
    setHover(best);
  };

  return (
    <div ref={box} className="svg-chart" data-testid="payoff-chart">
      <div className="chart-readout" aria-live="polite">
        {shown ? (
          <>
            <span className="muted">At {price(shown.underlying)}</span>
            <span className={shown.at_expiry >= 0 ? "up" : "down"}>
              {rupees(shown.at_expiry, { sign: true })} at expiry
            </span>
            {shown.today !== null && (
              <span className="accent-ink">{rupees(shown.today, { sign: true })} today</span>
            )}
          </>
        ) : (
          <span className="muted">Point at the chart to read the P&amp;L at a price.</span>
        )}
      </div>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label="Payoff at expiry and today"
          onPointerMove={move}
          onPointerLeave={() => setHover(null)}
        >
          <defs>
            <clipPath id={`${clip}-up`}>
              <rect x={0} y={0} width={width} height={Math.max(zero, 0)} />
            </clipPath>
            <clipPath id={`${clip}-down`}>
              <rect x={0} y={zero} width={width} height={Math.max(height - zero, 0)} />
            </clipPath>
          </defs>
          {ticks(lo, hi, 4).map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} className="grid" />
              <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" className="axis">
                {short(v)}
              </text>
            </g>
          ))}
          {ticks(first.underlying, last.underlying, 6).map((v) => (
            <text key={v} x={x(v)} y={height - 6} textAnchor="middle" className="axis">
              {qty(v)}
            </text>
          ))}
          <path d={area} className="area-up" clipPath={`url(#${clip}-up)`} />
          <path d={area} className="area-down" clipPath={`url(#${clip}-down)`} />
          <line x1={PAD.left} x2={width - PAD.right} y1={zero} y2={zero} className="zero" />
          <line x1={x(spot)} x2={x(spot)} y1={PAD.top} y2={height - PAD.bottom} className="spot" />
          {payoff.breakevens.map((b) => (
            <circle key={b} cx={x(b)} cy={zero} r={3.5} className="breakeven" />
          ))}
          {today && <path d={today} className="today" />}
          <path d={expiry} className="expiry" />
          {shown && (
            <g>
              <line
                x1={x(shown.underlying)}
                x2={x(shown.underlying)}
                y1={PAD.top}
                y2={height - PAD.bottom}
                className="cross"
              />
              <circle cx={x(shown.underlying)} cy={y(shown.at_expiry)} r={3.5} className="dot" />
            </g>
          )}
        </svg>
      )}
    </div>
  );
}

export interface ByStrike {
  strike: number;
  call: number | null;
  put: number | null;
}

/** Implied volatility across strikes, calls and puts, the money marked. */
export function SmileChart({
  rows,
  atm,
  height = 200,
}: {
  rows: ByStrike[];
  atm: number;
  height?: number;
}) {
  const [box, width] = useWidth<HTMLDivElement>();
  const values = rows.flatMap((r) => [r.call, r.put]).filter((v): v is number => v !== null);
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (!first || !last || values.length === 0) {
    return <div className="chart-note">No volatility to draw yet.</div>;
  }
  const lo = Math.floor(Math.min(...values) - 0.5);
  const hi = Math.ceil(Math.max(...values) + 0.5);
  const left = 36;
  const x = scale([first.strike, last.strike], [left, Math.max(width - PAD.right, left + 1)]);
  const y = scale([lo, hi], [height - PAD.bottom, PAD.top]);
  const path = (pick: (r: ByStrike) => number | null) => {
    const kept = rows.filter((r) => pick(r) !== null);
    return line(
      kept.map((r) => x(r.strike)),
      kept.map((r) => y(pick(r) as number)),
    );
  };
  return (
    <div ref={box} className="svg-chart">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Implied volatility by strike">
          {ticks(lo, hi, 4).map((v) => (
            <g key={v}>
              <line x1={left} x2={width - PAD.right} y1={y(v)} y2={y(v)} className="grid" />
              <text x={left - 6} y={y(v) + 4} textAnchor="end" className="axis">
                {v}%
              </text>
            </g>
          ))}
          {ticks(first.strike, last.strike, 4).map((v) => (
            <text key={v} x={x(v)} y={height - 6} textAnchor="middle" className="axis">
              {qty(v)}
            </text>
          ))}
          <line x1={x(atm)} x2={x(atm)} y1={PAD.top} y2={height - PAD.bottom} className="spot" />
          <path d={path((r) => r.call)} className="calls" />
          <path d={path((r) => r.put)} className="puts" />
        </svg>
      )}
    </div>
  );
}

/** Open interest at each strike, calls beside puts, in lakh. */
export function OiChart({
  rows,
  atm,
  height = 200,
}: {
  rows: ByStrike[];
  atm: number;
  height?: number;
}) {
  const [box, width] = useWidth<HTMLDivElement>();
  const most = Math.max(0, ...rows.flatMap((r) => [r.call ?? 0, r.put ?? 0]));
  const first = rows[0];
  if (!first || most === 0) return <div className="chart-note">No open interest to draw yet.</div>;
  const left = 36;
  const band = (Math.max(width - PAD.right, left + 1) - left) / rows.length;
  const bar = Math.max(1, band / 2 - 1);
  const y = scale([0, most * 1.08], [height - PAD.bottom, PAD.top]);
  const labelEvery = Math.ceil(rows.length / 5);
  return (
    <div ref={box} className="svg-chart">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Open interest by strike">
          {ticks(0, most, 3).map((v) => (
            <g key={v}>
              <line x1={left} x2={width - PAD.right} y1={y(v)} y2={y(v)} className="grid" />
              <text x={left - 6} y={y(v) + 4} textAnchor="end" className="axis">
                {(v / 1e5).toFixed(0)}L
              </text>
            </g>
          ))}
          {rows.map((r, n) => {
            const at = left + n * band;
            return (
              <g key={r.strike}>
                {r.strike === atm && (
                  <rect
                    x={at}
                    y={PAD.top}
                    width={band}
                    height={height - PAD.bottom - PAD.top}
                    className="atm-band"
                  />
                )}
                <rect
                  x={at + 0.5}
                  y={y(r.call ?? 0)}
                  width={bar}
                  height={y(0) - y(r.call ?? 0)}
                  className="bar-calls"
                />
                <rect
                  x={at + 0.5 + bar + 1}
                  y={y(r.put ?? 0)}
                  width={bar}
                  height={y(0) - y(r.put ?? 0)}
                  className="bar-puts"
                />
                {n % labelEvery === 0 && (
                  <text x={at + band / 2} y={height - 6} textAnchor="middle" className="axis">
                    {qty(r.strike)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
