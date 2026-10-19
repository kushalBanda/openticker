import { LineStyle } from "lightweight-charts";

// One look for every lightweight-charts chart (DESIGN.md Price Chart). The
// library draws on canvas, so colours are read from the CSS tokens at mount
// and again whenever the theme changes.

export const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const crossLine = () => ({
  color: token("--ink-muted"),
  style: LineStyle.Dashed,
  labelBackgroundColor: token("--ink"),
});

/**
 * The chart's frame: axes in `axis` type, `chart-grid` lines, a dashed
 * crosshair labelled in `ink`. `bare` hides the axes and horizontal hair
 * for a chart that draws its own scale (the Today hero's session line).
 */
export function chartFrame({
  grid = "both",
  bare = false,
}: {
  grid?: "both" | "rows" | "none";
  bare?: boolean;
} = {}) {
  const lines = token("--chart-grid");
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
      vertLines: grid === "both" ? { color: lines } : { visible: false },
      horzLines: grid === "none" ? { visible: false } : { color: lines },
    },
    rightPriceScale: bare ? { visible: false } : { borderColor: token("--line") },
    timeScale: bare ? { borderVisible: false } : { borderColor: token("--line") },
    crosshair: {
      vertLine: crossLine(),
      horzLine: bare ? { visible: false, labelVisible: false } : crossLine(),
    },
  };
}

/** Candles: rising in `up`, falling in `down`, body, border and wick alike. */
export function candleColours() {
  const up = token("--up");
  const down = token("--down");
  return {
    upColor: up,
    borderUpColor: up,
    wickUpColor: up,
    downColor: down,
    borderDownColor: down,
    wickDownColor: down,
  };
}

/**
 * A baseline at 0: `up` line over `up-soft` above, `down` under `down-soft`
 * below. `fade` lets the fill thin out away from the line, for a small chart.
 */
export function baselineColours({ fade = false }: { fade?: boolean } = {}) {
  return {
    topLineColor: token("--up"),
    topFillColor1: token("--up-soft"),
    topFillColor2: fade ? "transparent" : token("--up-soft"),
    bottomLineColor: token("--down"),
    bottomFillColor1: fade ? "transparent" : token("--down-soft"),
    bottomFillColor2: token("--down-soft"),
  };
}

/** Calls `repaint` whenever the theme changes; returns the way to stop. */
export function onThemeChange(repaint: () => void): () => void {
  const observer = new MutationObserver(repaint);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}
