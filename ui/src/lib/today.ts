// The Dashboard's words and numbers (ADR 34): the "since you were here"
// sentence, the tab's title, the daily calendar. Plain functions.

import type { Schemas } from "../api/client";
import { symbolName } from "./events";
import { istClock, rupees } from "./format";

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
