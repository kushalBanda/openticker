import type { Schemas } from "../api/client";
import { duration } from "./scripts";
import { askedBy } from "./strategies";

// What the Agents page says about MCP clients (ADR 35) and agent jobs (ADR 29).

type Job = Schemas["AgentJobResult"];

export const CONNECT = {
  claude: "claude mcp add openticker -- uv run openticker-mcp",
  codex: "codex mcp add openticker -- uv run openticker-mcp",
};

const CLIENTS: Record<string, string> = { "claude-code": "Claude Code", codex: "Codex" };

/** "Claude Code" for claude-code; other clients as they named themselves. */
export function clientLabel(name: string): string {
  return CLIENTS[name] ?? name;
}

export function harnessLabel(harness: string): string {
  return harness === "codex" ? "Codex" : "Claude Code";
}

export type JobState =
  | "waiting"
  | "running"
  | "stopping"
  | "finished"
  | "stopped"
  | "timed_out"
  | "failed"
  | "refused";

const STATES: Record<JobState, { label: string; tone?: "accent" | "down" }> = {
  waiting: { label: "Waiting", tone: "accent" },
  running: { label: "Running", tone: "accent" },
  stopping: { label: "Stopping", tone: "accent" },
  finished: { label: "Finished" },
  stopped: { label: "Stopped" },
  timed_out: { label: "Timed out", tone: "down" },
  failed: { label: "Failed", tone: "down" },
  refused: { label: "Not run" },
};

export function jobState(job: Job): JobState {
  if (job.status === "pending") return "waiting";
  if (job.status === "running") return "running";
  if (job.status === "stopping") return "stopping";
  switch (job.end_reason) {
    case "finished":
      return "finished";
    case "stopped":
    case "daemon_stopped":
      return "stopped";
    case "timeout":
      return "timed_out";
    case "refused":
      return "refused";
    default:
      return "failed";
  }
}

export function jobBadge(state: JobState) {
  return STATES[state];
}

/** How long it ran, or has run; null before it starts. */
export function took(job: Job, now: Date): string | null {
  if (!job.started_at) return null;
  const end = job.ended_at ? new Date(job.ended_at) : now;
  return duration(end.getTime() - new Date(job.started_at).getTime());
}

/** Why it ran: "asked by you", "every 1d", "12 runs after costs since the last review". */
export function why(trigger: string): string {
  if (trigger.startsWith("schedule: ")) return trigger.slice("schedule: ".length);
  return askedBy(trigger);
}
