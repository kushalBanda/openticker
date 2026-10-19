// The desk manager (ADR 41): plain functions of what get_manager returns.

import type { Schemas } from "../api/client";
import { istMinute, rupees } from "./format";
import { CLOSE, istDay, istMinutes, istShift, OPEN, toClock } from "./session";
import { reasonLabel } from "./strategies";

export type ManagerLine = Schemas["ManagerLineResult"];
export type DayFigure = Schemas["DayFigureResult"];
export type RunEnd = Schemas["RunEndResult"];

/** Market P&L before charges: closed trades, plus what's open where it's counted. */
export function market(figure: DayFigure): number {
  return Math.round((figure.gross + (figure.open ?? 0)) * 100) / 100;
}

// Ends that mean something went wrong, not that the run did what it was set to.
const FAULTS = new Set(["tick_stale", "error", "recovery_failed", "kill", "daily_loss_limit"]);

/**
 * How a strategy's last run ended, when that was today (`today`: the IST
 * date, YYYY-MM-DD): "Stopped at 13:33: prices lost". Null otherwise.
 */
export function endedToday(
  end: RunEnd | null | undefined,
  today: string,
): { text: string; fault: boolean } | null {
  if (!end?.at || end.at.slice(0, 10) !== today) return null;
  const why = reasonLabel(end.reason) ?? "stopped";
  return {
    text: `Stopped at ${end.at.slice(11, 16)}: ${why}`,
    fault: FAULTS.has(end.reason ?? ""),
  };
}

/** A line's row label: its strategy's or script's name, or what it stands for. */
export function lineLabel(line: Pick<ManagerLine, "key" | "name">): string {
  if (line.key === "desk") return "Desk";
  if (line.key === "own") return "Its own trades";
  if (line.name) return line.name;
  return line.key.startsWith("script:") ? "(deleted script)" : "(deleted strategy)";
}

/** Desk last, as the table's total; its own trades after the strategies and scripts. */
export function tableOrder<L extends { key: string }>(lines: L[]): L[] {
  const rank = (key: string) => (key === "desk" ? 2 : key === "own" ? 1 : 0);
  return [...lines].sort((a, b) => rank(a.key) - rank(b.key));
}

export function setByLabel(setBy: ManagerLine["set_by"]): string {
  return setBy === "you" ? "You" : "Manager";
}

/**
 * What the user typed for an amount, in rupees: "6,00,000", "₹6,00,000",
 * "-6000", "6.5L"; blank is none. undefined when it can't be read.
 */
export function parseRupees(text: string): number | null | undefined {
  const t = text.replace(/[₹,\s]/g, "").toLowerCase();
  if (t === "" || t === "—") return null;
  const found = /^(-?\d+(?:\.\d+)?)(k|l|cr)?$/.exec(t);
  if (!found) return undefined;
  const scale = { k: 1e3, l: 1e5, cr: 1e7 }[found[2] ?? ""] ?? 1;
  return Math.round(Number(found[1]) * scale * 100) / 100;
}

/** A stop is a loss: "5000" typed into a stop means -5,000. */
export function asStop(value: number): number {
  return -Math.abs(value);
}

/** The manager's numbers beside a line the user set, when they differ. */
export function disagreement(line: ManagerLine): string | null {
  if (line.set_by !== "you") return null;
  const capital = line.manager_capital !== line.capital ? line.manager_capital : undefined;
  const stop = line.manager_stop !== line.stop ? line.manager_stop : undefined;
  const parts: string[] = [];
  if (capital !== undefined && capital !== null) parts.push(rupees(capital, { decimals: 0 }));
  if (stop !== undefined && stop !== null) parts.push(`stop ${rupees(stop, { decimals: 0 })}`);
  return parts.length ? `Manager wanted ${parts.join(", ")}` : null;
}

const WAKES: Record<string, string> = {
  plan: "the plan",
  asked: "you asked",
  broke: "something broke",
  line: "a line crossed",
  scheduled: "its own time",
  fallback: "its hourly look",
  close: "after the close",
};

/** Why the manager woke, from ManagerWoke's reason or a turn's trigger ("manager-wake:plan"). */
export function wakeLabel(reasonOrTrigger: string): string {
  const reason = reasonOrTrigger.replace(/^manager-wake:/, "");
  return WAKES[reason] ?? reason;
}

/** A turn the user sent in the manager's thread, not a wake. */
export function isWake(trigger: string): boolean {
  return trigger.startsWith("manager-wake:");
}

/** What a plan wake was told (ADR 42): what broke since the last close, and what it answered then. */
export type WakeFacts = { from: string | null; since: string[]; close: string | null };

const tag = (prompt: string, name: string) =>
  prompt.match(new RegExp(`<${name}([^>]*)>\\n([\\s\\S]*?)\\n</${name}>`));

/** The facts a plan wake's message carries, or null when it carries none. */
export function wakeFacts(prompt: string | null | undefined): WakeFacts | null {
  if (!prompt) return null;
  const since = tag(prompt, "since_last_close");
  if (!since) return null;
  const [, attributes = "", body = ""] = since;
  const close = tag(prompt, "yesterdays_close")?.[2] ?? null;
  return {
    from: attributes.match(/from="([^"]+)"/)?.[1] ?? null,
    since: body
      .split("\n")
      .filter((line) => line.startsWith("- "))
      .map((line) => line.slice(2)),
    close: close && !close.startsWith("No close answer") ? close : null,
  };
}

type Turn = Schemas["AgentTurnResult"];
type Step = Schemas["StepResult"];

/** What the manager is doing right now, in a few words. */
export function nowDoing(
  enabled: boolean,
  turns: readonly Turn[],
  nextWakeAt: string | null,
  when: (at: string) => string,
): { tone: "accent" | "warn" | undefined; text: string } {
  const open = turns.findLast((t) => t.job.status !== "ended");
  if (open?.job.status === "pending") return { tone: "warn", text: "Waiting to start a look" };
  if (open) {
    const step = open.steps.at(-1);
    return { tone: "accent", text: step ? `Looking: ${stepText(step)}` : "Looking: starting up" };
  }
  if (!enabled) return { tone: undefined, text: "Off: it won't wake on its own" };
  return { tone: undefined, text: nextWakeAt ? `Idle until ${when(nextWakeAt)}` : "Idle" };
}

/** One step of a running look: the tool it calls, or what it's at. */
export function stepText(step: Step): string {
  if (step.kind === "thinking") return "thinking";
  if (step.kind === "text") return "writing its answer";
  if (step.kind === "error") return `an error${step.text ? `: ${step.text}` : ""}`;
  return step.tool ? `${step.tool}${step.summary ? ` (${step.summary})` : ""}` : "working";
}

/** What its looks cost so far: dollars where the harness reported them. */
export function spent(turns: readonly Turn[]): { usd: number | null; tokens: number } {
  let usd: number | null = null;
  let tokens = 0;
  for (const { job } of turns) {
    if (job.cost_usd != null) usd = (usd ?? 0) + job.cost_usd;
    tokens += (job.input_tokens ?? 0) + (job.output_tokens ?? 0);
  }
  return { usd, tokens };
}

/** Which of the user's two choices a look ran on (ADR 42): check-ins are the time it set and the hourly look. */
export type LookTier = "decisive" | "check";

export function lookTier(trigger: string): LookTier | null {
  if (!isWake(trigger)) return null;
  const reason = trigger.replace(/^manager-wake:/, "");
  return reason === "scheduled" || reason === "fallback" ? "check" : "decisive";
}

/** The day the rail draws: from the plan, 15 minutes before the open, to just after the close. */
export const RAIL = { from: 9 * 60, to: 15 * 60 + 45, open: OPEN, close: CLOSE };

/** Where on the rail a minute of the day sits, 0 to 100, held to the rail. */
export function railPct(minutes: number): number {
  const pct = ((minutes - RAIL.from) / (RAIL.to - RAIL.from)) * 100;
  return Math.round(Math.min(100, Math.max(0, pct)) * 10) / 10;
}

export type RailLook = {
  id: string;
  at: string; // HH:MM, IST
  pct: number;
  tier: LookTier;
  label: string; // "The plan"
  model: string | null; // as the harness reported, else as asked
  effort: string | null;
  cost: number | null;
};

/**
 * Today's looks on the rail, oldest first, and where the stretch it never
 * saw ends: its first look when that came after the open (it was turned on
 * mid-day), else null.
 */
export function railLooks(turns: readonly Turn[]): { looks: RailLook[]; offUntil: number | null } {
  const looks: (RailLook & { startedAt: string })[] = [];
  for (const { job } of turns) {
    const tier = lookTier(job.trigger);
    if (!tier) continue;
    const at = job.started_at ?? job.created_at;
    const minutes = istMinutes(at);
    const label = wakeLabel(job.trigger);
    looks.push({
      id: job.job_id,
      at: toClock(minutes),
      pct: railPct(minutes),
      tier,
      label: label.charAt(0).toUpperCase() + label.slice(1),
      model: job.model_used ?? job.model ?? null,
      effort: job.effort ?? null,
      cost: job.cost_usd ?? null,
      startedAt: at,
    });
  }
  // The first look of the day came after the open: it was off until then.
  const first = looks[0];
  const offUntil = first && istMinutes(first.startedAt) > RAIL.open ? first.pct : null;
  return { looks: looks.map(({ startedAt: _, ...look }) => look), offUntil };
}

/** The next look, as the tile's headline says it. */
export function nextLook(
  enabled: boolean,
  nextWakeAt: string | null,
  nextWakeReason: string | null,
  now: Date,
): { when: string; why: string } {
  if (!enabled)
    return { when: "Off", why: "It won't wake on its own. Turn it on to plan the day." };
  const today = istMinutes(now);
  if (nextWakeAt) {
    const wake = istShift(nextWakeAt);
    const sameDay = istDay(new Date(nextWakeAt)) === istDay(now);
    const hhmm = toClock(istMinutes(nextWakeAt));
    const weekday = wake.toLocaleDateString("en-IN", { weekday: "short", timeZone: "UTC" });
    return {
      // Short enough for a stat card; the why carries the words.
      when: sameDay ? hhmm : `${weekday} ${hhmm}`,
      why: nextWakeReason
        ? `${nextWakeReason.replace(/\.$/, "")}. Breakages wake it sooner.`
        : "The time it set. Breakages wake it sooner.",
    };
  }
  if (today >= RAIL.close || today < RAIL.from)
    return {
      when: "09:00",
      why: `The plan, 15 minutes before ${today < RAIL.from ? "the" : "the next"} open.`,
    };
  return { when: "Within the hour", why: "Its hourly look, unless something breaks first." };
}

/** An effort as a 1–5 gauge over the model's own levels; 0 for the harness's default. */
export function effortLevel(effort: string | null | undefined, levels: readonly string[]): number {
  if (!effort) return 0;
  const i = levels.indexOf(effort);
  if (i < 0 || levels.length === 0) return 3;
  return Math.max(1, Math.round(((i + 1) / levels.length) * 5));
}

/** A date some days before another, both "YYYY-MM-DD"; negative goes after. */
export function daysBefore(day: string, days: number): string {
  const at = new Date(`${day}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() - days);
  return at.toISOString().slice(0, 10);
}

/**
 * The tape's window, `reach` calendar days ending today; a day picked before
 * it moves the window to centre on it.
 */
export function tapeWindow(selected: string, today: string, reach: number): [string, string] {
  if (selected >= daysBefore(today, reach)) return [daysBefore(today, reach), today];
  const end = daysBefore(selected, -Math.floor(reach / 2));
  return [daysBefore(end, reach), end];
}

/** Which of these trading days, oldest first, start a new week (Monday to Sunday). */
export function tapeWeeks(days: readonly string[]): Set<number> {
  // Days since a Monday long ago, then the week each falls in.
  const week = (day: string) =>
    Math.floor((Date.parse(`${day}T00:00:00Z`) - Date.parse("2001-01-01T00:00:00Z")) / 604_800_000);
  return new Set(
    days.flatMap((day, i) => {
      const before = days[i - 1];
      return before !== undefined && week(day) !== week(before) ? [i] : [];
    }),
  );
}

/**
 * Each day's bar on the tape, 0 to 1 of the tallest: on a square root, so
 * one bad day doesn't flatten the rest, and never so small it can't be seen.
 * A day without a figure, or flat, has none.
 */
export function tapeHeights(nets: readonly (number | null)[]): number[] {
  const most = Math.max(0, ...nets.map((net) => Math.abs(net ?? 0)));
  return nets.map((net) =>
    !net || most === 0 ? 0 : Math.max(0.12, Math.sqrt(Math.abs(net) / most)),
  );
}

export type LineChange = Schemas["LineChangeResult"];

/**
 * A line's change in a phrase, "11:20 stop −₹4,000 by you": its time, what
 * moved since the change before it (both, for the day's first), who, and why.
 */
export function changeText(change: LineChange, before?: LineChange): string {
  const at = istMinute(new Date(change.at));
  // The day's first names what it set; a later one, what it moved (to none, too).
  const moved = (now: number | null, was: number | null | undefined) =>
    before ? now !== was : now != null;
  const amount = (value: number | null) =>
    value == null ? "none" : rupees(value, { decimals: 0 });
  const parts = [];
  if (moved(change.stop, before?.stop)) parts.push(`stop ${amount(change.stop)}`);
  if (moved(change.capital, before?.capital)) parts.push(`capital ${amount(change.capital)}`);
  const who = change.kept_yours
    ? "wanted by the manager; yours stood"
    : change.set_by === "you"
      ? "by you"
      : "by the manager";
  const why = change.reason && change.reason !== "set by you" ? `: ${change.reason}` : "";
  const when = change.after_close ? ", for the next day" : "";
  return `${at} ${parts.join(", ") || "no change"} ${who}${why}${when}`;
}

export type ManagerPlan = Schemas["ManagerPlanResult"];
export type PlanItem = Schemas["PlanItemResult"];
export type PlanCall = PlanItem["call"];

/** The plan's groups, in the order the page shows them (ADR 45). */
export const PLAN_CALLS: { call: PlanCall; title: string }[] = [
  { call: "runs", title: "Runs" },
  { call: "holds", title: "Holds open legs" },
  { call: "sits_out", title: "Sits out" },
];

/** An item's name: the strategy's or script's when the plan was set, else what it stands for. */
export function planItemLabel(item: Pick<PlanItem, "key" | "name">): string {
  if (item.key === "own") return "Its own trades";
  return item.name ?? item.key.replace(/^(strategy|script):/, "");
}

/** Where an item's page is, when it has one. */
export function planItemHref(key: string): string | null {
  const [kind, id] = key.split(":");
  if (!id) return null;
  return kind === "strategy" ? `/strategies/${id}` : kind === "script" ? `/scripts/${id}` : null;
}

/**
 * The plan's items grouped by their call, each with its line now (today's
 * plan only: a past day's lines at the close are the table below it).
 * Groups with nothing in them are left out.
 */
export function planGroups(
  items: PlanItem[],
  lines: ManagerLine[] | null,
): { call: PlanCall; title: string; items: { item: PlanItem; line: ManagerLine | null }[] }[] {
  const byKey = new Map((lines ?? []).map((l) => [l.key, l]));
  return PLAN_CALLS.map(({ call, title }) => ({
    call,
    title,
    items: items
      .filter((i) => i.call === call)
      .map((item) => ({ item, line: byKey.get(item.key) ?? null })),
  })).filter((g) => g.items.length > 0);
}

/**
 * The desk's net today against its stop: how much of the stop is used (0
 * to 1) and the rupees left before it's crossed. Null without a stop or a
 * figure.
 */
export function deskRoom(
  net: number | null | undefined,
  stop: number | null | undefined,
): { used: number; left: number } | null {
  if (net == null || stop == null || stop >= 0) return null;
  const used = Math.min(Math.max(net / stop, 0), 1);
  return { used, left: Math.max(net - stop, 0) };
}
