import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineStyle,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { applyTick, type Candle, type Choice, type Fill, fillMarks } from "../lib/candles";

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const SHOWN = 120; // candles in view when a range loads; wheel and drag for more

const two = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const when = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC", // times are the exchange's clock written as UTC (lib/candles)
});
const onDay = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

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
    grid: {
      vertLines: { color: token("--chart-grid") },
      horzLines: { color: token("--chart-grid") },
    },
    rightPriceScale: { borderColor: token("--line") },
    timeScale: { borderColor: token("--line") },
    crosshair: {
      vertLine: {
        color: token("--ink-muted"),
        style: LineStyle.Dashed,
        labelBackgroundColor: token("--ink"),
      },
      horzLine: {
        color: token("--ink-muted"),
        style: LineStyle.Dashed,
        labelBackgroundColor: token("--ink"),
      },
    },
  };
}

function seriesColours(dayUp: boolean) {
  const up = token("--up");
  const down = token("--down");
  return {
    upColor: up,
    borderUpColor: up,
    wickUpColor: up,
    downColor: down,
    borderDownColor: down,
    wickDownColor: down,
    priceLineColor: dayUp ? up : down,
  };
}

/**
 * One instrument's candles (DESIGN.md Price Chart): the paper fills marked
 * on the candle they fell in, buys below in `up`, sells above in `down`;
 * a dashed last-price line in the day's direction. Each tick moves the last
 * candle, or starts the next, through `update()`: the chart never redraws.
 * Wheel to zoom, drag to pan.
 */
export function CandleChart({
  candles,
  choice,
  live,
  fills,
  dayUp,
  height = 440,
}: {
  candles: Candle[];
  choice: Choice;
  /** The newest price and when it traded. */
  live?: { price: number; at: string };
  fills: Fill[];
  dayUp: boolean;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const last = useRef<Candle | undefined>(undefined);
  const first = useRef(0);
  const up = useRef(dayUp);
  up.current = dayUp;

  useEffect(() => {
    if (!box.current) return;
    const day = choice.minutes === 0;
    const made = createChart(box.current, {
      ...colours(),
      height,
      autoSize: true,
      timeScale: { timeVisible: !day, secondsVisible: false, rightOffset: 4 },
      localization: {
        priceFormatter: (v: number) => two.format(v),
        timeFormatter: (time: Time) => {
          const date = new Date((time as number) * 1000);
          return day ? onDay.format(date) : `${when.format(date)} IST`;
        },
      },
    });
    const line = made.addSeries(CandlestickSeries, {
      ...seriesColours(up.current),
      priceLineStyle: LineStyle.Dashed,
      priceLineWidth: 1,
    });
    series.current = line;
    markers.current = createSeriesMarkers(line, []);
    chart.current = made;
    const theme = new MutationObserver(() => {
      made.applyOptions(colours());
      series.current?.applyOptions(seriesColours(up.current));
    });
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      theme.disconnect();
      made.remove();
      chart.current = null;
      series.current = null;
      markers.current = null;
    };
  }, [height, choice]);

  useEffect(() => {
    series.current?.applyOptions({ priceLineColor: token(dayUp ? "--up" : "--down") });
  }, [dayUp]);

  // A new range: every candle at once, the latest in view.
  useEffect(() => {
    const data = candles.map((c) => ({ ...c, time: c.time as UTCTimestamp }));
    series.current?.setData(data);
    last.current = candles.at(-1);
    first.current = candles[0]?.time ?? 0;
    if (box.current) box.current.dataset.lastClose = String(last.current?.close ?? "");
    if (candles.length) {
      chart.current
        ?.timeScale()
        .setVisibleLogicalRange({ from: candles.length - SHOWN, to: candles.length + 3 });
    }
  }, [candles]);

  // Each tick: the last candle moves, or the next starts.
  useEffect(() => {
    if (!live || !last.current) return;
    const next = applyTick(last.current, live.price, live.at, choice);
    if (next === last.current) return;
    last.current = next;
    series.current?.update({ ...next, time: next.time as UTCTimestamp });
    if (box.current) box.current.dataset.lastClose = String(next.close);
  }, [live, choice]);

  // Marks on candles that exist, again when a new one starts.
  const lastTime = last.current?.time;
  useEffect(() => {
    if (lastTime === undefined) return;
    const marks = fillMarks(fills, choice, first.current, lastTime);
    markers.current?.setMarkers(
      marks.map((mark) =>
        mark.side === "BUY"
          ? {
              time: mark.time as UTCTimestamp,
              position: "belowBar" as const,
              shape: "arrowUp" as const,
              color: token("--up"),
              text: mark.text,
            }
          : {
              time: mark.time as UTCTimestamp,
              position: "aboveBar" as const,
              shape: "arrowDown" as const,
              color: token("--down"),
              text: mark.text,
            },
      ),
    );
    if (box.current) box.current.dataset.marks = String(marks.length);
  }, [fills, choice, lastTime]);

  return (
    <div
      ref={box}
      className="chart candle-chart"
      style={{ height }}
      data-testid="candle-chart"
      role="img"
      aria-label={`Candles, ${choice.label}, with your paper fills marked`}
    />
  );
}
