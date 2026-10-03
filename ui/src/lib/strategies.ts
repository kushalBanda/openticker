import type { Schemas } from "../api/client";
import { rupees } from "./format";

// What the strategies pages say about a strategy: its state and what comes
// next, its definition in words, a review's verdict, and its open legs'
// P&L marked to market with each tick (ADR 32).

export type Strategy = Schemas["StrategySummary"];
export type StrategyState = Schemas["StrategyState"];
export type RunLeg = Schemas["RunLegResult"];
export type Verdict = NonNullable<Schemas["ReviewBriefResult"]["verdict"]>;
export type OptionsDefinition = Schemas["StrategyDefinition"];
export type SignalDefinition = Schemas["SignalStrategyDefinition"];

export type KindFilter = "all" | "options" | "signal";
export type SegmentFilter = "all" | Schemas["Segment"];
export type StateFilter = "all" | "running" | "scheduled" | "stopped" | "killed";

const STATES: Record<StrategyState, { label: string; tone?: "accent" | "down" }> = {
  running: { label: "Running", tone: "accent" },
  listening: { label: "Listening", tone: "accent" },
  scheduled: { label: "Scheduled" },
  stopped: { label: "Stopped" },
  killed: { label: "Killed", tone: "down" },
};

export function stateBadge(state: StrategyState): { label: string; tone?: "accent" | "down" } {
  return STATES[state];
}

/** A signal strategy waiting on alerts counts as running; filters don't split them. */
export function matches(
  strategy: Strategy,
  kind: KindFilter,
  segment: SegmentFilter,
  state: StateFilter,
): boolean {
  const shown = strategy.state === "listening" ? "running" : strategy.state;
  return (
    (kind === "all" || strategy.kind === kind) &&
    (segment === "all" || strategy.segments.includes(segment)) &&
    (state === "all" || shown === state)
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const istParts = (at: string) => {
  const date = new Date(at);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return {
    weekday: get("weekday"),
    day: get("day"),
    month: get("month"),
    time: `${get("hour")}:${get("minute")}`,
  };
};

const istDay = (at: Date | string) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(at));

/** True when `at` falls on today's date in IST. */
export function isToday(at: string, now: Date): boolean {
  return istDay(at) === istDay(now);
}

/** "09:20" today, "Mon 09:20" within a week, else "5 Oct 09:20". */
export function when(at: string, now: Date): string {
  const p = istParts(at);
  if (istDay(at) === istDay(now)) return p.time;
  const days = (new Date(at).getTime() - now.getTime()) / 86_400_000;
  if (days > 0 && days < 6.5) return `${p.weekday} ${p.time}`;
  return `${p.day} ${p.month} ${p.time}`;
}

/** "today", "3 d ago", "1 w ago", "2 mo ago". */
export function ago(at: string, now: Date): string {
  if (istDay(at) === istDay(now)) return "today";
  const days = Math.max(1, Math.round((now.getTime() - new Date(at).getTime()) / 86_400_000));
  if (days < 7) return `${days} d ago`;
  if (days < 30) return `${Math.floor(days / 7)} w ago`;
  return `${Math.floor(days / 30)} mo ago`;
}

/** The line under a state: when it exits, enters, or what it waits on. */
export function stateNote(strategy: Strategy, now: Date): string | null {
  if (strategy.pending === "kill") return "closing legs";
  if (strategy.pending === "stop") return "stopping";
  if (strategy.pending === "start") return "starting";
  switch (strategy.state) {
    case "running":
      if (strategy.kind === "signal") return "on alert";
      return strategy.exit_time ? `exit ${strategy.exit_time.slice(0, 5)}` : "until stopped";
    case "listening":
      return "on alert";
    case "scheduled":
      return strategy.next_entry ? when(strategy.next_entry, now) : null;
    case "stopped":
      return strategy.last_run_at ? `last ran ${ago(strategy.last_run_at, now)}` : "never run";
    case "killed":
      return null;
  }
}

/** One row's quick action: Stop while running, Start when idle, Release when killed. */
export function quickAction(strategy: Strategy): "start" | "stop" | "release" | null {
  if (strategy.pending === "kill" || strategy.pending === "stop") return null;
  if (strategy.state === "killed") return "release";
  if (strategy.state === "running" && strategy.active_run) return "stop";
  if (
    strategy.kind === "options" &&
    (strategy.state === "stopped" || strategy.state === "scheduled")
  )
    return "start";
  return null;
}

/** What it trades, in the list's second line: "NIFTY 50, 2 legs" or "RELIANCE". */
export function trades(strategy: Strategy): string {
  if (strategy.kind === "signal") return strategy.underlying;
  return `${strategy.underlying}, ${strategy.legs} leg${strategy.legs === 1 ? "" : "s"}`;
}

const VERDICTS: Record<Verdict, { label: string; tone?: "up" | "down" | "warn" }> = {
  keep: { label: "Keep", tone: "up" },
  change: { label: "Change", tone: "warn" },
  retire: { label: "Retire", tone: "down" },
  not_yet: { label: "Not yet" },
};

export function verdictBadge(verdict: Verdict | null | undefined) {
  return verdict ? VERDICTS[verdict] : null;
}

export interface LegMark {
  side: "BUY" | "SELL";
  quantity: number;
  entry_price: number | null;
  status: RunLeg["status"];
  realized_pnl: number;
}

/**
 * A leg's P&L: realized once closed; while open, marked to `ltp`. Null when
 * an open leg has no entry or no price yet, never 0.
 */
export function legPnl(leg: LegMark, ltp: number | null | undefined): number | null {
  if (leg.status === "closed") return leg.realized_pnl;
  if (leg.status === "failed" || leg.status === "pending") return 0;
  if (leg.entry_price === null || ltp == null) return null;
  const move = ltp - leg.entry_price;
  return (leg.side === "BUY" ? move : -move) * leg.quantity;
}

const EXPIRIES: Record<Schemas["RelativeExpiry"], string> = {
  weekly: "nearest weekly",
  next_week: "next weekly",
  monthly: "nearest monthly",
  next_month: "next monthly",
};

type Risk = { value: number; percent: boolean } | null | undefined;

/** 30% or ₹25.00 */
export function risk(value: Risk): string | null {
  if (!value) return null;
  return value.percent ? `${value.value}%` : rupees(value.value);
}

function strikeText(leg: Schemas["LegDefinition"]): string {
  if (leg.option_type === "FUT") return "";
  if (leg.fixed_strike != null) return ` ${leg.fixed_strike}`;
  if (leg.strike_offset === 0) return " ATM";
  // +n: n strikes out of the money for the leg's own type; -n: in it.
  return ` ${leg.strike_offset > 0 ? "OTM" : "ITM"} ${Math.abs(leg.strike_offset)}`;
}

/** "Sell CE ATM", "Buy PE OTM 8", "Buy FUT" */
export function legText(leg: Schemas["LegDefinition"]): string {
  return `${leg.side === "BUY" ? "Buy" : "Sell"} ${leg.option_type}${strikeText(leg)}`;
}

/** "Mon–Fri", "Mon", "Tue, Thu" */
export function weekdaysText(days: number[] | undefined): string {
  const sorted = [...(days ?? [0, 1, 2, 3, 4])].sort();
  if (sorted.join() === "0,1,2,3,4") return "Mon–Fri";
  return sorted.map((d) => WEEKDAYS[d]).join(", ");
}

export interface Line {
  label: string;
  value: string;
}

/** Everything a definition sets, in words, skipping what it leaves unset. */
export function optionsLines(d: OptionsDefinition): Line[] {
  const lines: Line[] = [
    { label: "Underlying", value: `${d.underlying} · ${d.exchange}` },
    { label: "Expiry", value: [...new Set(d.legs.map((l) => EXPIRIES[l.expiry]))].join(", ") },
    { label: "Legs", value: d.legs.map(legText).join(" · ") },
    {
      label: "Lots",
      value:
        [...new Set(d.legs.map((l) => l.lots))].length === 1
          ? `${d.legs[0]?.lots ?? 0} each`
          : d.legs.map((l) => l.lots).join(" / "),
    },
  ];
  const stops = [...new Set(d.legs.map((l) => risk(l.stop_loss)).filter(Boolean))];
  if (stops.length) lines.push({ label: "Leg stop", value: stops.join(" / ") });
  const targets = [...new Set(d.legs.map((l) => risk(l.target)).filter(Boolean))];
  if (targets.length) lines.push({ label: "Leg target", value: targets.join(" / ") });
  return [...lines, ...limitLines(d), ...scheduleLines(d)];
}

export function signalLines(d: SignalDefinition): Line[] {
  const lines: Line[] = d.legs.map((leg, i) => ({
    label: d.legs.length === 1 ? "Instrument" : `Leg ${i + 1}`,
    value: `${leg.symbol} · ${leg.quantity.toLocaleString("en-IN")}${
      leg.accepts === "both" ? "" : leg.accepts === "long_only" ? " · long only" : " · short only"
    }`,
  }));
  lines.push({
    label: "Direction",
    value: { both: "long and short", long_only: "long only", short_only: "short only" }[
      d.direction
    ],
  });
  const leg = d.legs[0];
  if (d.legs.length === 1 && leg && (leg.stop_loss || leg.target)) {
    lines.push({
      label: "Stop / target",
      value: `${risk(leg.stop_loss) ?? "—"} / ${risk(leg.target) ?? "—"}`,
    });
  }
  return [...lines, ...limitLines(d), ...scheduleLines(d)];
}

function limitLines(d: OptionsDefinition | SignalDefinition): Line[] {
  const lines: Line[] = [];
  if (d.combined_stop_loss != null)
    lines.push({ label: "Combined stop", value: rupees(d.combined_stop_loss) });
  if (d.combined_target != null)
    lines.push({ label: "Combined target", value: rupees(d.combined_target) });
  if (d.lock_profit)
    lines.push({
      label: d.lock_profit.mode === "lock" ? "Lock" : "Lock / trail",
      value: `lock ${rupees(d.lock_profit.lock, { decimals: 0 })} at ${rupees(d.lock_profit.arm_at, { decimals: 0 })}`,
    });
  if (d.daily_loss_limit != null)
    lines.push({ label: "Daily loss limit", value: rupees(d.daily_loss_limit) });
  return lines;
}

function scheduleLines(d: OptionsDefinition | SignalDefinition): Line[] {
  const lines: Line[] = [{ label: "Product", value: d.horizon === "intraday" ? "MIS" : "NRML" }];
  const days = "weekdays" in d ? (d.weekdays as number[] | undefined) : undefined;
  if (d.entry_time)
    lines.push({ label: "Enters", value: `${weekdaysText(days)} ${d.entry_time.slice(0, 5)}` });
  if (d.exit_time) lines.push({ label: "Exits", value: d.exit_time.slice(0, 5) });
  return lines;
}

/** The request to copy for an agent: definitions are changed only there. */
export function changePrompt(strategy: { name: string; strategy_id: string }): string {
  return `Change the OpenTicker strategy "${strategy.name}" (${strategy.strategy_id}): `;
}

export const NEW_STRATEGY_PROMPT =
  "Write me a new OpenTicker paper strategy with the new-strategy skill: ";

/** "64% win" over the runs after costs; null before any. */
export function winRate(wins: number, judged: number): string | null {
  return judged > 0 ? `${Math.round((wins / judged) * 100)}% win` : null;
}

const TRIGGERS: Record<string, string> = {
  schedule: "Schedule",
  ui: "You",
  "mcp:claude-code": "Claude",
  "mcp:codex": "Codex",
  alert: "An alert",
  webhook: "An alert",
};

/** Who started a run or asked for a review: "You", "Claude", "Schedule", ... */
export function triggerLabel(trigger: string): string {
  const known = TRIGGERS[trigger];
  if (known) return known;
  if (trigger.startsWith("schedule")) return "Schedule";
  if (trigger.startsWith("mcp")) return "An agent";
  if (trigger.startsWith("rest:")) return `REST API (${trigger.slice(5)})`;
  if (trigger.startsWith("alert")) return "An alert";
  return trigger;
}

/** How a review came about: "on its schedule", "asked by you", "asked by Claude". */
export function askedBy(trigger: string): string {
  if (trigger.startsWith("schedule")) return "on its schedule";
  const label = triggerLabel(trigger);
  return `asked by ${label === "You" ? "you" : label}`;
}

const REASONS: Record<Schemas["StrategyStopReason"], string> = {
  manual: "stopped",
  kill: "killed",
  schedule: "exit time",
  expiry: "expiry day",
  combined_stop_loss: "combined stop",
  combined_target: "combined target",
  profit_lock: "profit lock",
  daily_loss_limit: "daily loss limit",
  tick_stale: "prices lost",
  recovery_failed: "recovery failed",
  error: "error",
  legs_closed: "legs closed",
};

export function reasonLabel(reason: Schemas["StrategyStopReason"] | null): string | null {
  return reason ? REASONS[reason] : null;
}

const MONTHS: Record<string, string> = {
  JAN: "01",
  FEB: "02",
  MAR: "03",
  APR: "04",
  MAY: "05",
  JUN: "06",
  JUL: "07",
  AUG: "08",
  SEP: "09",
  OCT: "10",
  NOV: "11",
  DEC: "12",
};
const CONTRACT = /^(.+?)(\d{2})([A-Z]{3})(\d{2})(FUT|([\d.]+)(CE|PE))$/;

/**
 * What a leg's symbol says about its contract, so it can be named Kite's
 * way: NIFTY29SEP2624800CE is a CE expiring 2026-09-29 at 24800.
 */
export function contractOf(symbol: string): {
  type: "EQ" | "FUT" | "CE" | "PE";
  expiry: string | null;
  strike: number | null;
} {
  const found = CONTRACT.exec(symbol);
  const month = found ? MONTHS[found[3] ?? ""] : undefined;
  if (!found || !month) return { type: "EQ", expiry: null, strike: null };
  const expiry = `20${found[4]}-${month}-${found[2]}`;
  if (found[5] === "FUT") return { type: "FUT", expiry, strike: null };
  return { type: found[7] as "CE" | "PE", expiry, strike: Number(found[6]) };
}
