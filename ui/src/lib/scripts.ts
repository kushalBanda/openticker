import type { Schemas } from "../api/client";
import { istClock, istDate, qty } from "./format";
import { weekdaysText } from "./strategies";

// What the Scripts pages say about a hosted script (ADR 25): its state, its
// schedule and its runs in words.

type Script = Schemas["ScriptResult"];
type Run = Schemas["ScriptRunResult"];
type Reason = NonNullable<Run["stop_reason"]>;

export type ScriptState =
  | "starting"
  | "running"
  | "stopping"
  | "finished"
  | "stopped"
  | "failed"
  | "never";

const STATES: Record<ScriptState, { label: string; tone?: "accent" | "down" }> = {
  starting: { label: "Starting", tone: "accent" },
  running: { label: "Running", tone: "accent" },
  stopping: { label: "Stopping", tone: "accent" },
  finished: { label: "Finished" },
  stopped: { label: "Stopped" },
  failed: { label: "Failed", tone: "down" },
  never: { label: "Never run" },
};

export function stateBadge(state: ScriptState) {
  return STATES[state];
}

const REASONS: Record<Reason, { said: string; state: ScriptState }> = {
  exited: { said: "exit 0", state: "finished" },
  failed: { said: "failed", state: "failed" },
  stopped: { said: "stopped", state: "stopped" },
  schedule: { said: "stopped on schedule", state: "stopped" },
  memory_limit: { said: "memory limit", state: "failed" },
  cpu_limit: { said: "CPU limit", state: "failed" },
  log_limit: { said: "printed too much", state: "failed" },
  daemon_stopped: { said: "server stopped", state: "stopped" },
  lost: { said: "lost in a restart", state: "failed" },
  start_failed: { said: "didn't start", state: "failed" },
};

/**
 * Where a script is now. `asked`: a start or stop sent from this page that
 * the daemon hasn't carried out yet.
 */
export function scriptState(script: Script, asked?: "start" | "stop"): ScriptState {
  const run = script.last_run;
  if (script.running && run?.status === "stopping") return "stopping";
  if (script.running) return asked === "stop" ? "stopping" : "running";
  if (asked === "start") return "starting";
  if (!run?.stop_reason) return "never";
  return REASONS[run.stop_reason].state;
}

/** Why a run ended, in a few words: "exit 0", "exit 1", "memory limit". */
export function endText(run: Run): string {
  if (!run.stop_reason) return "";
  if (run.stop_reason === "failed" && run.exit_code !== null) {
    return run.exit_code < 0 ? "killed" : `exit ${run.exit_code}`;
  }
  return REASONS[run.stop_reason].said;
}

/** "Mon–Fri 09:16–15:15", "Mon–Fri 09:10"; null: only when started. */
export function scheduleText(schedule: Script["schedule"]): string | null {
  if (!schedule) return null;
  const start = schedule.start_time.slice(0, 5);
  const stop = schedule.stop_time ? `–${schedule.stop_time.slice(0, 5)}` : "";
  return `${weekdaysText(schedule.weekdays)} ${start}${stop}`;
}

/** 42s, 3m 11s, 2h 26m. */
export function duration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** How long a run ran, or has run so far. */
export function runtime(run: Run, now: Date): string {
  const end = run.ended_at ? new Date(run.ended_at) : now;
  return duration(end.getTime() - new Date(run.started_at).getTime());
}

const istDay = (at: Date | string) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(at));

/** 09:16:00 today, "yesterday 10:02", else "19 Sep 10:02". */
export function stamp(at: string, now: Date): string {
  if (istDay(at) === istDay(now)) return istClock(new Date(at));
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (istDay(at) === istDay(yesterday)) return `yesterday ${istClock(new Date(at)).slice(0, 5)}`;
  return istDate(at, { time: true });
}

/** "since 09:16:00" while it runs; "09:10:00, exit 0" once it ended. */
export function lastRunText(run: Run | null, now: Date): string | null {
  if (!run) return null;
  if (!run.ended_at) return `since ${stamp(run.started_at, now)}`;
  return `${stamp(run.started_at, now)}, ${endText(run)}`;
}

/** "84 / 256 MB": the run's peak against the limit. */
export function memoryText(
  peakMb: number | null | undefined,
  limitMb: number | undefined,
): string | null {
  if (peakMb == null) return null;
  const used = qty(Math.round(peakMb));
  return limitMb === undefined ? `${used} MB` : `${used} / ${qty(limitMb)} MB`;
}

/** At or over its memory limit: the figure turns red. */
export function atLimit(peakMb: number | null | undefined, limitMb: number | undefined): boolean {
  return peakMb != null && limitMb !== undefined && peakMb >= limitMb;
}

/** Who started a run, as a person says it. */
export function startedBy(trigger: string): string {
  if (trigger === "schedule") return "its schedule";
  if (trigger === "recovery") return "a restart";
  if (trigger === "ui") return "you";
  if (trigger.startsWith("mcp:claude")) return "Claude";
  if (trigger.startsWith("mcp:codex")) return "Codex";
  if (trigger.startsWith("mcp")) return "an agent";
  if (trigger.startsWith("rest:")) return `key ${trigger.slice(5)}`;
  return trigger;
}

export const NEW_SCRIPT_PROMPT =
  "Write me an OpenTicker hosted script and upload it with upload_script: ";
