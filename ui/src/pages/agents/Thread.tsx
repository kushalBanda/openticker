import type { UseQueryResult } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Copy, Ellipsis, PanelRight, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useReducer, useState } from "react";
import { useNavigate } from "react-router";
import {
  type AgentStep,
  type AgentThread,
  type AgentThreadSummary,
  type AgentTurn,
  type ChatChange,
  useAgentJobLog,
  useDeleteThread,
  useEditQueued,
  useRemoveQueued,
  useUpdateThread,
} from "../../api/queries";
import { Dialog } from "../../components/Dialog";
import { Markdown } from "../../components/Markdown";
import {
  activeTurn,
  answerOf,
  queuedTurn,
  ranLine,
  whereLabel,
  workedFor,
  workSteps,
} from "../../lib/threads";
import { useActions } from "../../shell/actions";
import { useServerNow } from "../../stream/StreamProvider";
import { ChangedCard, changesIn } from "./Changes";

const CodeView = lazy(() =>
  import("../../components/CodeView").then((m) => ({ default: m.CodeView })),
);

/** A background run with no steps to show (Codex's, or one from before chats): what it printed. */
export function Printed({ jobId }: { jobId: string }) {
  const log = useAgentJobLog(jobId);
  if (log.isPending) return null;
  if (log.isError) {
    return (
      <p className="note" role="alert">
        What it printed didn't load: {log.error.message}
      </p>
    );
  }
  return (
    <>
      <div className="label job-log-label">What it printed</div>
      {log.data.log ? (
        <div className="code-tile aw-printed">
          <Suspense fallback={<div className="skeleton" style={{ height: "100%" }} />}>
            <CodeView language="log" label="What the agent printed" text={log.data.log} />
          </Suspense>
        </div>
      ) : (
        <p className="note">It printed nothing.</p>
      )}
    </>
  );
}

function StepRow({ step }: { step: AgentStep }) {
  if (step.kind === "thinking") return <div className="aw-st">Thinking</div>;
  if (step.kind === "text") return <div className="aw-st">{step.text}</div>;
  return (
    <div className="aw-st" data-failed={step.failed}>
      {step.tool && <code>{step.tool}</code>}
      {step.summary && <span>{step.summary}</span>}
      {step.kind === "error" && <span>{step.text}</span>}
      {step.failed && step.result && <span className="aw-st-why">{step.result}</span>}
    </div>
  );
}

/** Re-renders every second while `on`: "Working for 12s" counts up. */
function useEverySecond(on: boolean) {
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (!on) return;
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [on]);
}

function TurnView({
  turn: read,
  streamed,
  changes,
}: {
  turn: AgentTurn;
  streamed?: AgentStep[];
  changes: readonly ChatChange[];
}) {
  const serverNow = useServerNow();
  const live = read.job.status !== "ended";
  // While it runs, the stream's steps; once it ended, the chat as read again.
  const turn = live && streamed ? { ...read, steps: streamed } : read;
  useEverySecond(live);
  const [open, setOpen] = useState(false);
  const steps = workSteps(turn);
  const answer = answerOf(turn);
  // Why the harness says the turn failed: its own words, not folded away.
  const failure = turn.steps.findLast((step) => step.kind === "error")?.text;
  const shown = open || live;
  const Chevron = shown ? ChevronDown : ChevronRight;
  return (
    <>
      {turn.job.prompt && <div className="aw-you">{turn.job.prompt}</div>}
      <div className="aw-agent">
        {live && steps.length === 0 && (
          <div className="aw-worked" aria-live="polite">
            {workedFor(turn, serverNow())}
          </div>
        )}
        {steps.length > 0 && (
          <button
            type="button"
            className="aw-worked"
            aria-expanded={shown}
            onClick={() => setOpen(!open)}
          >
            {workedFor(turn, serverNow())}
            <Chevron aria-hidden />
          </button>
        )}
        {shown && steps.length > 0 && (
          <div className="aw-steps">
            {steps.map((step, i) => (
              // Steps never reorder; a turn only appends.
              // biome-ignore lint/suspicious/noArrayIndexKey: append-only list
              <StepRow key={i} step={step} />
            ))}
          </div>
        )}
        {!live && answer && answer !== failure && <Markdown text={answer} />}
        {!live && turn.job.kind !== "chat" && turn.steps.length === 0 && (
          <Printed jobId={turn.job.job_id} />
        )}
        {!live && failure && (
          <p className="error-line" role="alert">
            {failure}
          </p>
        )}
        {!live && turn.job.end_detail && turn.job.end_reason !== "finished" && (
          <p className="note" role={failure ? undefined : "alert"}>
            {turn.job.end_detail}
          </p>
        )}
        {turn.job.kind === "chat" && <ChangedCard entries={changesIn(changes, turn)} />}
        {!live && (
          <div className="aw-foot">
            <div className="aw-acts">
              <button
                type="button"
                className="aw-ico"
                aria-label="Copy answer"
                onClick={() => answer && navigator.clipboard.writeText(answer)}
              >
                <Copy aria-hidden />
              </button>
              <button type="button" className="aw-ico" aria-label="More" disabled>
                <Ellipsis aria-hidden />
              </button>
            </div>
            <span className="aw-ran">{ranLine(turn.job)}</span>
          </div>
        )}
      </div>
    </>
  );
}

/** One chat: its head, then each turn's message, folded steps and answer. */
export function Thread({
  query,
  live: streamed,
  changes,
  panel,
  onPanel,
}: {
  query: UseQueryResult<AgentThread, Error>;
  live: Map<string, AgentStep[]>;
  changes: readonly ChatChange[];
  panel: boolean;
  onPanel: () => void;
}) {
  if (query.isPending) {
    return <div className="aw-scroll scroll" aria-busy="true" />;
  }
  if (query.isError) {
    return (
      <div className="aw-scroll scroll">
        <p className="note aw-thread" role="alert">
          This chat didn't load: {query.error.message}
        </p>
      </div>
    );
  }
  const thread = query.data;
  const queued = queuedTurn(thread.turns);
  // The turn the agent is on decides the badge, not a message waiting behind it.
  const last = (activeTurn(thread.turns) ?? thread.turns.at(-1))?.job;
  const live = last && last.status !== "ended";
  return (
    <>
      <header className="aw-head">
        <h2>{thread.title}</h2>
        <span className="aw-where">{whereLabel(thread)}</span>
        {live && (
          <span className="badge" data-tone="accent">
            {last.kind === "chat" ? "Replying" : "Running"}
          </span>
        )}
        {thread.archived && <Restore threadId={thread.thread_id} />}
        <span className="flex-1" />
        <button
          type="button"
          className="aw-ico"
          aria-label={panel ? "Hide side panel" : "Show side panel"}
          aria-pressed={panel}
          title="Side panel  ⌥⌘B"
          onClick={onPanel}
        >
          <PanelRight aria-hidden />
        </button>
        <DeleteChat thread={thread} working={Boolean(live)} />
      </header>
      <div className="aw-scroll scroll">
        <div className="aw-thread">
          {thread.turns.map((turn) =>
            turn === queued ? (
              <QueuedPill key={turn.job.job_id} threadId={thread.thread_id} turn={turn} />
            ) : (
              <TurnView
                key={turn.job.job_id}
                turn={turn}
                streamed={streamed.get(turn.job.job_id)}
                changes={changes}
              />
            ),
          )}
        </div>
      </div>
    </>
  );
}

/** A follow-up waiting for the agent's turn to end: edit it or take it back
 * until the agent takes it. */
function QueuedPill({ threadId, turn }: { threadId: string; turn: AgentTurn }) {
  const edit = useEditQueued(threadId);
  const remove = useRemoveQueued(threadId);
  const [draft, setDraft] = useState<string | null>(null);
  const jobId = turn.job.job_id;
  const save = () => {
    const message = draft?.trim();
    if (!message) return;
    edit.mutate({ jobId, message }, { onSuccess: () => setDraft(null) });
  };
  const failed = edit.error ?? remove.error;
  return (
    <div className="aw-queued">
      {draft === null ? (
        <div className="aw-you aw-queued-text">{turn.job.prompt}</div>
      ) : (
        <textarea
          className="aw-queued-edit"
          aria-label="Edit the waiting message"
          // biome-ignore lint/a11y/noAutofocus: opened by the Edit click, to type in at once
          autoFocus
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              save();
            }
            if (e.key === "Escape") setDraft(null);
          }}
        />
      )}
      <div className="aw-queued-meta">
        {draft === null ? (
          <>
            <span>Queued. Sends when this turn ends.</span>
            <button
              type="button"
              className="link-button"
              onClick={() => setDraft(turn.job.prompt ?? "")}
            >
              Edit
            </button>
            <button
              type="button"
              className="link-button"
              disabled={remove.isPending}
              onClick={() => remove.mutate(jobId)}
            >
              Remove
            </button>
          </>
        ) : (
          <>
            <button type="button" className="link-button" onClick={() => setDraft(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="link-button"
              disabled={edit.isPending || !draft.trim()}
              onClick={save}
            >
              Save
            </button>
          </>
        )}
      </div>
      {failed && (
        <p className="note" role="alert">
          {failed.message}
        </p>
      )}
    </div>
  );
}

/** An archived chat says so and comes back to the list in one click. */
function Restore({ threadId }: { threadId: string }) {
  const update = useUpdateThread();
  return (
    <>
      <span className="badge" data-tone="muted">
        Archived
      </span>
      <button
        type="button"
        className="btn"
        data-size="sm"
        data-variant="ghost"
        disabled={update.isPending}
        onClick={() => update.mutate({ threadId, change: { archived: false } })}
      >
        Restore
      </button>
    </>
  );
}

/** Deletes the chat once the agent is off it; what the agent did stays. */
function DeleteChat({ thread, working }: { thread: AgentThread; working: boolean }) {
  const [asking, setAsking] = useState(false);
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        className="aw-ico"
        aria-label="Delete chat"
        title={working ? "Stop the agent to delete this chat" : "Delete chat"}
        disabled={working}
        onClick={() => setAsking(true)}
      >
        <Trash2 aria-hidden />
      </button>
      <DeleteChatDialog
        thread={thread}
        open={asking}
        onClose={() => setAsking(false)}
        onDeleted={() => navigate("/agents")}
      />
    </>
  );
}

/** Asks once before a chat leaves the web app, and says what stays. */
export function DeleteChatDialog({
  thread,
  open,
  onClose,
  onDeleted,
}: {
  thread: AgentThreadSummary;
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const remove = useDeleteThread(thread.thread_id);
  const { notify } = useActions();
  return (
    <Dialog open={open} onClose={onClose} title="Delete this chat?">
      <div className="dialog-body">
        <p className="note">
          “{thread.title}” leaves the web app. What the agent changed stays, and its runs stay under
          Connected agents and jobs.
        </p>
        {remove.isError && (
          <p className="error-line" role="alert">
            Not deleted: {remove.error.message}
          </p>
        )}
      </div>
      <div className="dialog-foot">
        <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(undefined, {
              onSuccess: () => {
                onClose();
                notify("Chat deleted");
                onDeleted();
              },
            })
          }
        >
          Delete chat
        </button>
      </div>
    </Dialog>
  );
}
