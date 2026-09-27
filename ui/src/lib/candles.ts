// The Symbol page's candles: intervals, their ranges, where a tick or a
// fill falls. lightweight-charts shows times as UTC, so every time here is
// the exchange's clock time written as UTC: the axis reads IST with no zone.

import type { Interval } from "../api/queries";

export interface Candle {
  time: number; // seconds, exchange clock time as UTC
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface Choice {
  interval: Interval;
  label: string;
  /** Calendar days of history asked for. */
  days: number;
  /** Minutes a candle spans; 0 for a day. */
  minutes: number;
}

export const CHOICES: Choice[] = [
  { interval: "minute", label: "1m", days: 4, minutes: 1 },
  { interval: "5minute", label: "5m", days: 14, minutes: 5 },
  { interval: "15minute", label: "15m", days: 40, minutes: 15 },
  { interval: "60minute", label: "1h", days: 120, minutes: 60 },
  { interval: "day", label: "Day", days: 400, minutes: 0 },
];

export const choiceOf = (interval: Interval): Choice =>
  CHOICES.find((c) => c.interval === interval) ?? (CHOICES[1] as Choice);

const IST_MS = 330 * 60_000;
const OPEN_MINUTE = 9 * 60 + 15; // candles count from 09:15, as Kite's do

/** An instant as exchange clock time in seconds ("10:30 IST" becomes 10:30 UTC). */
export function clockSeconds(at: string | Date): number {
  return Math.floor(((typeof at === "string" ? Date.parse(at) : at.getTime()) + IST_MS) / 1000);
}

/** The start of the candle `at` falls in. */
export function bucket(at: string | Date, choice: Choice): number {
  const seconds = clockSeconds(at);
  const day = seconds - (seconds % 86_400);
  if (choice.minutes === 0) return day;
  const minute = Math.floor((seconds - day) / 60);
  const since = minute - OPEN_MINUTE;
  const start = OPEN_MINUTE + Math.floor(since / choice.minutes) * choice.minutes;
  return day + start * 60;
}

/** A price at `at` applied to the candles: the last one moves, or a new one starts. */
export function applyTick(
  last: Candle | undefined,
  price: number,
  at: string | Date,
  choice: Choice,
): Candle {
  const time = bucket(at, choice);
  if (!last || time > last.time)
    return { time, open: price, high: price, low: price, close: price };
  if (time < last.time) return last; // late: the chart never goes back
  return {
    ...last,
    high: Math.max(last.high, price),
    low: Math.min(last.low, price),
    close: price,
  };
}

/** The date `days` before `today` (YYYY-MM-DD, both exchange dates). */
export function daysBefore(today: string, days: number): string {
  const d = new Date(`${today}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export interface Fill {
  filled_at: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
}

export interface FillMark {
  time: number;
  side: "BUY" | "SELL";
  text: string;
}

/**
 * One mark per candle and side: several buys in one candle are one arrow
 * ("B 15"), placed on the candle they fell in. Only candles on the chart.
 */
export function fillMarks(fills: Fill[], choice: Choice, first: number, last: number): FillMark[] {
  const marks = new Map<string, FillMark & { units: number }>();
  for (const fill of fills) {
    const time = bucket(fill.filled_at, choice);
    if (time < first || time > last) continue;
    const key = `${time}:${fill.side}`;
    const was = marks.get(key);
    const units = (was?.units ?? 0) + fill.quantity;
    marks.set(key, {
      time,
      side: fill.side,
      units,
      text: `${fill.side === "BUY" ? "B" : "S"} ${units}`,
    });
  }
  return [...marks.values()]
    .sort((a, b) => a.time - b.time)
    .map(({ time, side, text }) => ({ time, side, text }));
}
