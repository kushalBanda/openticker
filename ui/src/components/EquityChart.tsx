import { BaselineSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baselineColours, chartFrame, onThemeChange } from "../lib/chart";

export interface EquityPoint {
  day: string; // YYYY-MM-DD
  net_pnl: number;
}

/**
 * A strategy's net P&L after costs, day by day, as a baseline at 0 (DESIGN.md
 * Price Chart): above in `up`, below in `down`. Drawn once; colours follow the
 * theme.
 */
export function EquityChart({ points, height = 200 }: { points: EquityPoint[]; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const made = createChart(box.current, {
      ...chartFrame({ grid: "rows" }),
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
      ...baselineColours(),
    });
    chart.current = made;
    const stop = onThemeChange(() => {
      made.applyOptions(chartFrame({ grid: "rows" }));
      series.current?.applyOptions(baselineColours());
    });
    return () => {
      stop();
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
