// The Dashboard's words and numbers (ADR 34): the "since you were here"
// sentence, the tab's title, the daily calendar. Plain functions.

import type { Schemas } from "../api/client";
import { symbolName } from "./events";
import { istClock, rupees } from "./format";
import { OPEN, toClock, toMinutes } from "./session";

type Since = Schemas["SinceResult"];
type Entry = Since["events"][number];

export interface Part {
  text: string;
  to?: string; // where it happened
  tone?: "up" | "down";
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const text = (entry: Entry, key: string) => {
  const value = entry.details[key];
  return typeof value === "string" ? value : "";
};

function eventPart(entry: Entry, names: ReadonlyMap<string, string>, times: number): Part {
  const id = text(entry, "strategy_id");
  const name = names.get(id) ?? (text(entry, "name") || "A strategy");
  switch (entry.event_type) {
    case "StrategyStopped":
      return {
        text: text(entry, "reason") === "kill" ? `${name} was killed` : `${name} stopped`,
        to: id ? `/strategies/${id}` : undefined,
      };
    case "BrokerSessionExpired":
      return { text: `the ${cap(text(entry, "broker"))} session expired`, to: "/settings" };
    case "OrderFailed":
      return {
        text:
          times > 1
            ? `${times} orders for ${symbolName(text(entry, "symbol"))} were refused`
            : `an order for ${symbolName(text(entry, "symbol"))} was refused`,
        to: "/orders",
      };
    default:
      return { text: entry.event_type };
  }
}

/** "Since you were here at 11:02: 2 fills, SBIN mean reversion was killed, and you're +₹2,140.00." */
export function sinceSentence(
  since: Since,
  names: ReadonlyMap<string, string> = new Map(),
): { lead: string; parts: Part[] } {
  const at = istClock(new Date(since.at)).slice(0, 5);
  const parts: Part[] = [];
  if (since.fills) {
    parts.push({ text: `${since.fills} fill${since.fills === 1 ? "" : "s"}`, to: "/trades" });
  }
  // The same thing twice is said once: "2 orders for TCS were refused".
  const alike = new Map<string, { entry: Entry; times: number }>();
  for (const entry of since.events) {
    const key = eventPart(entry, names, 1).text;
    const seen = alike.get(key);
    if (seen) seen.times += 1;
    else alike.set(key, { entry, times: 1 });
  }
  for (const { entry, times } of alike.values()) parts.push(eventPart(entry, names, times));
  if (since.more_events) parts.push({ text: `${since.more_events} more`, to: "/activity" });
  if (!parts.length) return { lead: `Nothing's changed since ${at}.`, parts: [] };
  if (since.pnl_change !== null && since.pnl_change !== undefined) {
    parts.push({
      text: `you're ${rupees(since.pnl_change, { sign: true })}`,
      tone: since.pnl_change < 0 ? "down" : since.pnl_change > 0 ? "up" : undefined,
    });
  }
  return { lead: `Since you were here at ${at}: `, parts };
}

export interface CalendarDay {
  date: string; // YYYY-MM-DD
  net: number | null; // null: traded nothing recorded, or no price
  estimated: boolean;
}

/** Weeks of weekdays (Mon..Fri), oldest first, for the heatmap; null where no day. */
export function weeks(days: CalendarDay[], from: string, to: string): (CalendarDay | null)[][] {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const start = new Date(`${from}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7)); // back to Monday
  const end = new Date(`${to}T00:00:00Z`);
  const out: (CalendarDay | null)[][] = [];
  for (let day = start; day <= end; day.setUTCDate(day.getUTCDate() + 7)) {
    const week: (CalendarDay | null)[] = [];
    for (let i = 0; i < 5; i++) {
      const d = new Date(day);
      d.setUTCDate(d.getUTCDate() + i);
      const key = d.toISOString().slice(0, 10);
      week.push(
        key < from || key > to
          ? null
          : (byDate.get(key) ?? { date: key, net: null, estimated: false }),
      );
    }
    out.push(week);
  }
  return out;
}

/**
 * What the recorded days add up to: best, worst and winning days, the net
 * over all of them and on average, the latest month's net, and the run of
 * winning or losing days the latest day belongs to (a flat day ends a run).
 */
export function dayStats(days: CalendarDay[]) {
  const known = days.filter((d): d is CalendarDay & { net: number } => d.net !== null);
  if (!known.length) return null;
  const nets = known.map((d) => d.net);
  const total = nets.reduce((sum, n) => sum + n, 0);
  const latest = known.at(-1) as CalendarDay & { net: number };
  const month = latest.date.slice(0, 7);
  let streak = 0;
  for (let i = known.length - 1; i >= 0; i--) {
    const net = known[i]?.net ?? 0;
    if (net === 0 || Math.sign(net) !== Math.sign(latest.net)) break;
    streak++;
  }
  return {
    best: Math.max(...nets),
    worst: Math.min(...nets),
    winning: nets.filter((n) => n > 0).length,
    days: known.length,
    total,
    average: total / known.length,
    month: known.filter((d) => d.date.startsWith(month)).reduce((sum, d) => sum + d.net, 0),
    /** Days in the latest run: positive for winning days, negative for losing ones. */
    streak: Math.sign(latest.net) * streak,
  };
}

export interface PnlCandle {
  slot: string; // HH:MM the candle starts, exchange-local
  open: number;
  high: number;
  low: number;
  close: number;
}

/**
 * The minute line as candles of `every` minutes from 09:15. The P&L is a
 * point a minute, so high and low are the highest and lowest of those
 * points. A candle opens where the one just before it closed, as prices do;
 * after a gap with no points it opens at its own first point.
 */
export function pnlCandles(points: { minute: string; net_pnl: number }[], every = 5): PnlCandle[] {
  const start = OPEN;
  const candles: PnlCandle[] = [];
  for (const point of points) {
    const minutes = toMinutes(point.minute);
    if (minutes < start) continue;
    const slot = toClock(start + Math.floor((minutes - start) / every) * every);
    const last = candles.at(-1);
    if (last?.slot === slot) {
      last.high = Math.max(last.high, point.net_pnl);
      last.low = Math.min(last.low, point.net_pnl);
      last.close = point.net_pnl;
      continue;
    }
    const follows = last !== undefined && toMinutes(slot) - toMinutes(last.slot) === every;
    const open = follows ? last.close : point.net_pnl;
    candles.push({
      slot,
      open,
      high: Math.max(open, point.net_pnl),
      low: Math.min(open, point.net_pnl),
      close: point.net_pnl,
    });
  }
  return candles;
}
