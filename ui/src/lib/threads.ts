import type { AgentJob, AgentThreadSummary, AgentTurn, ChoiceKind, Script } from "../api/queries";
import { harnessLabel } from "./agents";
import type { Strategy } from "./strategies";

// What the Agents workspace says about chats and their turns (ADR 40).

export type FolderKind = "general" | "strategy" | "script" | "review" | "debrief";

const FOLDERS: Record<FolderKind, string> = {
  general: "General",
  strategy: "Strategies",
  script: "Scripts",
  review: "Reviews",
  debrief: "Debriefs",
};

export const FOLDER_ORDER: FolderKind[] = ["general", "strategy", "script", "review", "debrief"];

export function folderName(folder: FolderKind): string {
  return FOLDERS[folder];
}

const CHOICE_KINDS: Record<FolderKind, ChoiceKind> = {
  general: "general",
  strategy: "strategies",
  script: "scripts",
  review: "reviews",
  debrief: "debriefs",
};

/** The Settings default a chat in this folder starts from. */
export function choiceKind(folder: string): ChoiceKind {
  return CHOICE_KINDS[folder as FolderKind] ?? "general";
}

/** Where a chat lives, as the rail and the chat's head say it. */
export function whereLabel(thread: AgentThreadSummary): string {
  if (thread.folder === "general") return "General";
  if (thread.folder === "debrief") return thread.subject_name ?? "Debriefs";
  return thread.subject_name ?? `${FOLDERS[thread.folder as FolderKind]} · deleted`;
}

const DAY_MS = 86_400_000;
const IST = "Asia/Kolkata";
const istDay = new Intl.DateTimeFormat("en-CA", { timeZone: IST });
const weekday = new Intl.DateTimeFormat("en-GB", { timeZone: IST, weekday: "short" });
const dayMonth = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST,
  day: "numeric",
  month: "short",
});

/** When a chat last moved, as the rail shows it: "now", "12m", "2h", "Mon", "8 Oct". */
export function relativeTime(iso: string, now: Date): string {
  const at = new Date(iso);
  const ms = now.getTime() - at.getTime();
  if (ms < 60_000) return "now";
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (istDay.format(at) === istDay.format(now)) return `${Math.floor(ms / 3_600_000)}h`;
  if (ms < 6 * DAY_MS) return weekday.format(at);
  return dayMonth.format(at);
}

function seconds(ms: number): string {
  const s = Math.max(1, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** "Worked for 41s" once a turn ended; "Working for 12s" while it runs. */
export function workedFor(turn: AgentTurn, now: Date): string {
  const job = turn.job;
  if (job.status === "pending") return "Waiting to start";
  const start = job.started_at ? new Date(job.started_at).getTime() : now.getTime();
  if (job.status !== "ended") return `Working for ${seconds(now.getTime() - start)}`;
  const ms = job.duration_ms ?? (job.ended_at ? new Date(job.ended_at).getTime() - start : 0);
  return `Worked for ${seconds(ms)}`;
}

export function tokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

/** What ran: "Claude Code · claude-opus-5-5 · high · 38.4k tokens · $0.07". */
export function ranLine(job: AgentJob): string {
  const parts = [harnessLabel(job.harness)];
  const model = job.model_used ?? job.model;
  if (model) parts.push(model);
  if (job.effort) parts.push(job.effort);
  const used = (job.input_tokens ?? 0) + (job.output_tokens ?? 0);
  if (used > 0) parts.push(`${tokens(used)} tokens`);
  if (job.cost_usd != null) parts.push(`$${job.cost_usd.toFixed(2)}`);
  return parts.join(" · ");
}

/** A turn's answer: its last text step, else the job's summary. */
export function answerOf(turn: AgentTurn): string | null {
  for (let i = turn.steps.length - 1; i >= 0; i--) {
    const step = turn.steps[i];
    if (step?.kind === "text" && step.text) return step.text;
  }
  return turn.job.summary ?? null;
}

/** The steps before the answer: what "Worked for" folds away. */
export function workSteps(turn: AgentTurn) {
  const answer = answerOf(turn);
  const last = turn.steps.at(-1);
  return last?.kind === "text" && last.text === answer ? turn.steps.slice(0, -1) : turn.steps;
}

/** A question the empty chat offers, filed where it belongs. */
export type Suggestion = {
  text: string;
  folder: "general" | "strategy" | "script";
  subject: string | null;
  where: string;
};

const ENDED_BADLY = new Set([
  "failed",
  "memory_limit",
  "cpu_limit",
  "log_limit",
  "lost",
  "start_failed",
]);

/**
 * Up to three questions from the desk as it is now: the strategy down most
 * today, the last review's verdict, a script that stopped badly; the desk
 * as a whole when there is nothing more particular to ask.
 */
export function suggestions(strategies: Strategy[], scripts: Script[]): Suggestion[] {
  const found: Suggestion[] = [];
  const about = (s: Strategy, text: string) =>
    found.push({ text, folder: "strategy", subject: s.strategy_id, where: s.name });
  const down = [...strategies]
    .filter((s) => s.today_pnl < 0)
    .sort((a, b) => a.today_pnl - b.today_pnl)[0];
  if (down) about(down, `Why is ${down.name} down today?`);
  const reviewed = strategies
    .filter((s) => s.last_review?.verdict && s !== down)
    .sort((a, b) =>
      (b.last_review?.ended_at ?? "").localeCompare(a.last_review?.ended_at ?? ""),
    )[0];
  if (reviewed?.last_review?.verdict) {
    const verdict = reviewed.last_review.verdict.replaceAll("_", " ");
    about(reviewed, `What would change the "${verdict}" verdict on ${reviewed.name}?`);
  }
  const broken = scripts.find((s) => ENDED_BADLY.has(s.last_run?.stop_reason ?? ""));
  if (broken?.last_run?.stop_reason) {
    found.push({
      text: `Why did ${broken.name} stop (${broken.last_run.stop_reason.replaceAll("_", " ")})?`,
      folder: "script",
      subject: broken.script_id,
      where: broken.name,
    });
  }
  if (found.length < 3) {
    found.push({
      text: "What happened on my desk today?",
      folder: "general",
      subject: null,
      where: "General",
    });
  }
  return found.slice(0, 3);
}

/** A new chat that picks up where one that can't be continued left off:
 * its title and last answer as the first message, in the folder a chat can
 * start in (a review's strategy; General for a debrief). */
export function seedFrom(thread: AgentThreadSummary, lastAnswer: string | null): Suggestion {
  const excerpt = (lastAnswer ?? "").trim();
  const quoted = excerpt
    ? `\n\nIts last answer:\n> ${(excerpt.length > 600 ? `${excerpt.slice(0, 599)}…` : excerpt).replaceAll("\n", "\n> ")}`
    : "";
  const text = `Picking up from the chat "${thread.title}".${quoted}\n\n`;
  const name = thread.subject_name;
  if ((thread.folder === "strategy" || thread.folder === "review") && thread.subject && name) {
    return { text, folder: "strategy", subject: thread.subject, where: name };
  }
  if (thread.folder === "script" && thread.subject && name) {
    return { text, folder: "script", subject: thread.subject, where: name };
  }
  return { text, folder: "general", subject: null, where: "General" };
}

/** The message waiting behind the turn the agent is on, if one waits. */
export function queuedTurn(turns: readonly AgentTurn[]): AgentTurn | null {
  const at = turns.findIndex((t) => t.job.status === "pending");
  if (at <= 0) return null;
  return turns.slice(0, at).some((t) => t.job.status === "running" || t.job.status === "stopping")
    ? (turns[at] ?? null)
    : null;
}

/** The turn the agent is on now: running or stopping, else none. */
export function activeTurn(turns: readonly AgentTurn[]): AgentTurn | null {
  return turns.findLast((t) => t.job.status === "running" || t.job.status === "stopping") ?? null;
}
