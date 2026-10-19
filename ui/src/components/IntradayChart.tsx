import {
  BaselineSeries,
  type CandlestickData,
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineStyle,
  type Time,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import { baselineColours, candleColours, chartFrame, onThemeChange, token } from "../lib/chart";
import { rupees } from "../lib/format";
import { sessionAt, sessionMinutes, toClock, toMinutes } from "../lib/session";
import { pnlCandles } from "../lib/today";

export type IntradayStyle = "line" | "candles";

export interface MinutePoint {
  minute: string; // HH:MM, exchange-local
  net_pnl: number;
}

// Where each mark sits along the session, 09:15 to 15:30.
const MARKS = ["09:15", "12:00", "15:30"].map((label) => ({
  label,
  at: sessionAt(toMinutes(label)),
}));

// The chart shows its times as UTC: each minute is stored as that same
// clock time in UTC, so the axis reads exchange time without a zone.
function at(day: string, minute: string): UTCTimestamp {
  const [y, m, d] = day.split("-").map(Number);
  const [hh, mm] = minute.split(":").map(Number);
  return (Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0) / 1000) as UTCTimestamp;
}

const clock = (time: Time) => {
  const date = new Date((time as number) * 1000);
  return toClock(date.getUTCHours() * 60 + date.getUTCMinutes());
};

const SESSION = sessionMinutes();
const EVERY = 5; // minutes a candle
const SLOTS = SESSION.filter((_, i) => i % EVERY === 0);
const slotOf = (minute: string) => SLOTS[Math.floor(SESSION.indexOf(minute) / EVERY)];

/**
 * The day's P&L after charges, a point a minute (DESIGN.md Today Hero): the
 * axis is the whole session, so the line stops at now and the rest of the day
 * is still to come. A dashed zero line; above in `up`, below in `down`; a
 * mark where the user was last here. Drawn left to right once. As candles,
 * five minutes each; the one still forming is hollow until its five are up.
 */
export function IntradayChart({
  day,
  points: recorded,
  now,
  visit,
  height = 150,
  style = "line",
}: {
  day: string;
  points: MinutePoint[];
  /** The live figure at this minute, while the market is open: the line ends where the figure is. */
  now?: MinutePoint;
  /** HH:MM of the previous visit, marked on the line. */
  visit?: string;
  height?: number;
  style?: IntradayStyle;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const tip = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!box.current) return;
    const made = createChart(box.current, {
      ...chartFrame({ grid: "none", bare: true }),
      height,
      autoSize: true,
      handleScroll: false,
      handleScale: false,
      // The three time marks are drawn below the chart, where they belong on
      // a whole-session axis; the library's own ticks fall where they like.
      timeScale: { visible: false, minBarSpacing: 0.01, rightOffset: 0 },
      localization: {
        timeFormatter: (time: Time) => `${clock(time)} IST`,
        priceFormatter: (v: number) => Math.round(v).toLocaleString("en-IN"),
      },
    });
    const line =
      style === "candles"
        ? made.addSeries(CandlestickSeries, {
            priceLineVisible: false,
            lastValueVisible: false,
            ...candleColours(),
          })
        : made.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: 0 },
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerRadius: 3,
            ...baselineColours({ fade: true }),
          });
    const slots = style === "candles" ? SLOTS : SESSION;
    line.createPriceLine({
      price: 0,
      color: token("--line-strong"),
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      axisLabelVisible: false,
    });
    series.current = line;
    markers.current = createSeriesMarkers(line, []);
    chart.current = made;
    // Every minute of the session in view, whitespace included, at any width.
    const whole = () => made.timeScale().setVisibleLogicalRange({ from: 0, to: slots.length - 1 });
    const size = new ResizeObserver(whole);
    size.observe(box.current);
    // The figure under the pointer: the axes are hidden, so the crosshair
    // alone would say where without saying what.
    made.subscribeCrosshairMove((move) => {
      const el = tip.current;
      const width = box.current?.clientWidth ?? 0;
      const point = move.time !== undefined ? move.seriesData.get(line) : undefined;
      const value =
        point && "close" in point
          ? point.close
          : point && "value" in point
            ? point.value
            : undefined;
      if (!el || !move.point || !point || typeof value !== "number") {
        if (el) el.hidden = true;
        return;
      }
      el.hidden = false;
      el.dataset.tone = value < 0 ? "down" : value > 0 ? "up" : "";
      const figure = el.querySelector(".intraday-tip-value");
      const time = el.querySelector(".intraday-tip-time");
      if (figure) figure.textContent = rupees(value, { sign: true });
      if (time) {
        time.textContent =
          style === "candles"
            ? `${clock(point.time)}–${clock(((point.time as number) + EVERY * 60) as Time)}`
            : clock(point.time);
      }
      const half = el.offsetWidth / 2;
      el.style.left = `${Math.min(Math.max(move.point.x, half), width - half)}px`;
    });
    const stop = onThemeChange(() => {
      made.applyOptions(chartFrame({ grid: "none", bare: true }));
      series.current?.applyOptions(
        style === "candles" ? candleColours() : baselineColours({ fade: true }),
      );
    });
    return () => {
      size.disconnect();
      stop();
      made.remove();
      chart.current = null;
      series.current = null;
      markers.current = null;
    };
  }, [height, style]);

  const nowMinute = now?.minute;
  const nowNet = now?.net_pnl;
  const points = useMemo(() => {
    const last = recorded.at(-1);
    if (nowMinute === undefined || nowNet === undefined || !SESSION.includes(nowMinute)) {
      return recorded;
    }
    if (last && nowMinute < last.minute) return recorded;
    return [
      ...recorded.filter((p) => p.minute !== nowMinute),
      { minute: nowMinute, net_pnl: nowNet },
    ];
  }, [recorded, nowMinute, nowNet]);

  const live = nowMinute !== undefined && points.at(-1)?.minute === nowMinute;

  useEffect(() => {
    const last = points.at(-1);
    const seen = visit ? points.filter((p) => p.minute <= visit).at(-1) : undefined;
    const visitMark = seen
      ? [
          {
            time: at(day, style === "candles" ? (slotOf(seen.minute) ?? seen.minute) : seen.minute),
            position: "aboveBar" as const,
            shape: "arrowDown" as const,
            color: token("--ink-muted"),
            text: `you were here ${visit}`,
            size: 0.6,
          },
        ]
      : [];
    if (style === "candles") {
      const candles = pnlCandles(points, EVERY);
      const bySlot = new Map(candles.map((c) => [c.slot, c]));
      const forming = live ? candles.at(-1)?.slot : undefined;
      const data: (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] = SLOTS.map(
        (slot) => {
          const candle = bySlot.get(slot);
          if (!candle) return { time: at(day, slot) };
          const { open, high, low, close } = candle;
          const bar = { time: at(day, slot), open, high, low, close };
          if (slot !== forming) return bar;
          const tone = token(close < open ? "--down" : "--up");
          return { ...bar, color: "transparent", borderColor: tone, wickColor: tone };
        },
      );
      (series.current as ISeriesApi<"Candlestick"> | null)?.setData(data);
      markers.current?.setMarkers(visitMark);
    } else {
      const byMinute = new Map(points.map((p) => [p.minute, p.net_pnl]));
      const data: ({ time: UTCTimestamp; value: number } | WhitespaceData<UTCTimestamp>)[] =
        SESSION.map((minute) => {
          const value = byMinute.get(minute);
          return value === undefined ? { time: at(day, minute) } : { time: at(day, minute), value };
        });
      (series.current as ISeriesApi<"Baseline"> | null)?.setData(data);
      markers.current?.setMarkers([
        ...visitMark,
        ...(last
          ? [
              {
                time: at(day, last.minute),
                position: "atPriceMiddle" as const,
                price: last.net_pnl,
                shape: "circle" as const,
                color: token(last.net_pnl < 0 ? "--down" : "--up"),
                size: 0.8,
              },
            ]
          : []),
      ]);
    }
    const slots = style === "candles" ? SLOTS : SESSION;
    chart.current?.timeScale().setVisibleLogicalRange({ from: 0, to: slots.length - 1 }); // the whole session
  }, [day, points, visit, style, live]);

  return (
    <div className="intraday">
      <div ref={tip} className="intraday-tip" hidden aria-hidden data-testid="intraday-tip">
        <span className="intraday-tip-value tabular" />
        <span className="intraday-tip-time" />
      </div>
      <div
        ref={box}
        className="chart intraday-chart"
        style={{ height }}
        data-testid="intraday-chart"
        data-style={style}
        role="img"
        aria-label={
          points.length
            ? `Today's P&L after charges${style === "candles" ? ", in five-minute candles," : ""} from ${points[0]?.minute} to ${points.at(-1)?.minute}`
            : "No P&L points yet today"
        }
      />
      <div className="intraday-marks" aria-hidden>
        {MARKS.map((mark) => (
          <span key={mark.label} className="intraday-mark" style={{ left: `${mark.at * 100}%` }}>
            {mark.label}
          </span>
        ))}
      </div>
    </div>
  );
}
