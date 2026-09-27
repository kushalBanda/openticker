import {
  BaselineSeries,
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

export interface MinutePoint {
  minute: string; // HH:MM, exchange-local
  net_pnl: number;
}

// Where each mark sits along the session, 09:15 to 15:30.
const MARKS = [
  { label: "09:15", at: 0 },
  { label: "12:00", at: 165 / 375 },
  { label: "15:30", at: 1 },
];

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// The chart shows its times as UTC: each minute is stored as that same
// clock time in UTC, so the axis reads exchange time without a zone.
function at(day: string, minute: string): UTCTimestamp {
  const [y, m, d] = day.split("-").map(Number);
  const [hh, mm] = minute.split(":").map(Number);
  return (Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0) / 1000) as UTCTimestamp;
}

const clock = (time: Time) => {
  const date = new Date((time as number) * 1000);
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}`;
};

function sessionMinutes(): string[] {
  const out: string[] = [];
  for (let t = 9 * 60 + 15; t <= 15 * 60 + 30; t++) {
    out.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  }
  return out;
}
const SESSION = sessionMinutes();

function colours() {
  return {
    layout: {
      // TradingView is credited in Settings → App instead (the library's license allows it).
      attributionLogo: false,
      background: { color: "transparent" },
      textColor: token("--ink-muted"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11,
    },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    rightPriceScale: { visible: false },
    timeScale: { borderVisible: false },
    crosshair: {
      vertLine: {
        color: token("--ink-muted"),
        style: LineStyle.Dashed,
        labelBackgroundColor: token("--ink"),
      },
      horzLine: { visible: false, labelVisible: false },
    },
  };
}

function seriesColours() {
  return {
    topLineColor: token("--up"),
    topFillColor1: token("--up-soft"),
    topFillColor2: "transparent",
    bottomLineColor: token("--down"),
    bottomFillColor1: "transparent",
    bottomFillColor2: token("--down-soft"),
  };
}

/**
 * The day's P&L after charges, a point a minute (DESIGN.md Today Hero): the
 * axis is the whole session, so the line stops at now and the rest of the day
 * is still to come. A dashed zero line; above in `up`, below in `down`; a
 * mark where the user was last here. Drawn left to right once.
 */
export function IntradayChart({
  day,
  points: recorded,
  now,
  visit,
  height = 150,
}: {
  day: string;
  points: MinutePoint[];
  /** The live figure at this minute, while the market is open: the line ends where the figure is. */
  now?: MinutePoint;
  /** HH:MM of the previous visit, marked on the line. */
  visit?: string;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const made = createChart(box.current, {
      ...colours(),
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
    const line = made.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerRadius: 3,
      ...seriesColours(),
    });
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
    const whole = () =>
      made.timeScale().setVisibleLogicalRange({ from: 0, to: SESSION.length - 1 });
    const size = new ResizeObserver(whole);
    size.observe(box.current);
    const theme = new MutationObserver(() => {
      made.applyOptions(colours());
      series.current?.applyOptions(seriesColours());
    });
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      size.disconnect();
      theme.disconnect();
      made.remove();
      chart.current = null;
      series.current = null;
      markers.current = null;
    };
  }, [height]);

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

  useEffect(() => {
    const byMinute = new Map(points.map((p) => [p.minute, p.net_pnl]));
    const data: ({ time: UTCTimestamp; value: number } | WhitespaceData<UTCTimestamp>)[] =
      SESSION.map((minute) => {
        const value = byMinute.get(minute);
        return value === undefined ? { time: at(day, minute) } : { time: at(day, minute), value };
      });
    series.current?.setData(data);
    const last = points.at(-1);
    const seen = visit ? points.filter((p) => p.minute <= visit).at(-1) : undefined;
    markers.current?.setMarkers([
      ...(seen
        ? [
            {
              time: at(day, seen.minute),
              position: "aboveBar" as const,
              shape: "arrowDown" as const,
              color: token("--ink-muted"),
              text: `you were here ${visit}`,
              size: 0.6,
            },
          ]
        : []),
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
    chart.current?.timeScale().setVisibleLogicalRange({ from: 0, to: SESSION.length - 1 }); // the whole session
  }, [day, points, visit]);

  return (
    <div className="intraday">
      <div
        ref={box}
        className="chart intraday-chart"
        style={{ height }}
        data-testid="intraday-chart"
        role="img"
        aria-label={
          points.length
            ? `Today's P&L after charges from ${points[0]?.minute} to ${points.at(-1)?.minute}`
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
