import {
  BaselineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  LineStyle,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface EquityPoint {
  day: string; // YYYY-MM-DD
  net_pnl: number;
}

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
      vertLines: { visible: false },
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

function seriesColours() {
  return {
    topLineColor: token("--up"),
    topFillColor1: token("--up-soft"),
    topFillColor2: token("--up-soft"),
    bottomLineColor: token("--down"),
    bottomFillColor1: token("--down-soft"),
    bottomFillColor2: token("--down-soft"),
  };
}

/**
 * A strategy's net P&L after costs, day by day, as a baseline at 0 (DESIGN.md
 * Price Chart): above in `up`, below in `down`. Drawn once; colours follow the
 * theme. The library's attribution logo stays (its license).
 */
export function EquityChart({ points, height = 200 }: { points: EquityPoint[]; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const made = createChart(box.current, {
      ...colours(),
      height,
      autoSize: true,
      handleScroll: false,
      handleScale: false,
      localization: { priceFormatter: (v: number) => Math.round(v).toLocaleString("en-IN") },
    });
    series.current = made.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      ...seriesColours(),
    });
    chart.current = made;
    const theme = new MutationObserver(() => {
      made.applyOptions(colours());
      series.current?.applyOptions(seriesColours());
    });
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      theme.disconnect();
      made.remove();
      chart.current = null;
      series.current = null;
    };
  }, [height]);

  useEffect(() => {
    series.current?.setData(points.map((p) => ({ time: p.day, value: p.net_pnl })));
    chart.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={box} className="chart" style={{ height }} data-testid="equity-chart" />;
}
