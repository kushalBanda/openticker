import { ArrowUp, Folder, Lock, Plus, Square } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { useNavigate } from "react-router";
import {
  type AgentThread,
  type Effort,
  useAgentSettings,
  useHarnesses,
  useSendMessage,
  useStopThread,
} from "../../api/queries";
import { HarnessLogo } from "../../components/HarnessLogo";
import { harnessLabel } from "../../lib/agents";
import {
  activeTurn,
  answerOf,
  choiceKind,
  queuedTurn,
  seedFrom,
  whereLabel,
} from "../../lib/threads";
import { AccessChip } from "./AccessPicker";
import { type Choice, ChoicePicker } from "./ChoicePicker";

/** What a message in `folder` runs with unless it picks: the folder's
 * default from Settings, when that default is for this harness. */
export function useFolderDefault(harness: string, folder: string) {
  const settings = useAgentSettings().data;
  const info = useHarnesses().data?.harnesses.find((h) => h.harness === harness);
  const resolved = settings?.folders.find((f) => f.kind === choiceKind(folder))?.resolved;
  const mine = resolved?.harness === harness;
  return {
    info,
    folderDefault: {
      model: mine ? (resolved?.model ?? null) : null,
      effort: mine ? ((resolved?.effort ?? null) as Effort | null) : null,
    },
  };
}

/** The box under a chat: where it is, its harness, model and effort, send. */
export function Composer({ thread }: { thread: AgentThread }) {
  const send = useSendMessage(thread.thread_id);
  const stop = useStopThread(thread.thread_id);
  const [text, setText] = useState("");
  const [choice, setChoice] = useState<Choice>({ model: null, effort: null });
  const { info, folderDefault } = useFolderDefault(thread.harness, thread.folder);
  const active = activeTurn(thread.turns)?.job;
  const queued = queuedTurn(thread.turns);
  const last = active ?? thread.turns.at(-1)?.job;
  const working = last !== undefined && last.status !== "ended";
  // Sent while the agent works, a message waits its turn (one at a time).
  const ready = thread.continuable && !send.isPending;
  const queues = working && ready && text.trim() !== "";
  // Ended, yet nothing to continue: its conversation is gone, or never began.
  const closed = !thread.continuable && !working && last !== undefined;
  const navigate = useNavigate();

  const submit = () => {
    const message = text.trim();
    if (!message || !ready) return;
    send.mutate({ message, ...choice }, { onSuccess: () => setText("") });
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="aw-dock">
      <div className="aw-composer">
        <div className="aw-chips">
          <span className="aw-chip">
            <Folder aria-hidden />
            {whereLabel(thread)}
          </span>
          <span className="aw-chip" title="Fixed after the first message">
            <Lock aria-hidden />
            <HarnessLogo harness={thread.harness} size={14} />
            {harnessLabel(thread.harness)}
          </span>
          <AccessChip access={thread.access ?? "trade"} />
        </div>
        {closed && (
          <p className="note aw-closed" role="status">
            The agent can't continue this conversation.{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                const answer =
                  thread.turns
                    .filter((t) => t.job.end_reason === "finished")
                    .map(answerOf)
                    .filter(Boolean)
                    .at(-1) ?? null;
                navigate("/agents", { state: { seed: seedFrom(thread, answer) } });
              }}
            >
              Start a new chat with this context
            </button>
          </p>
        )}
        <div className="aw-box">
          <textarea
            aria-label="Message"
            placeholder={
              queued
                ? "One message waits for the agent: edit it above"
                : ready && working
                  ? last.kind === "chat"
                    ? "Queue a follow-up"
                    : `Queue a message for when the ${last.kind} ends`
                  : ready
                    ? last?.kind === "chat"
                      ? "Ask a follow-up"
                      : `Continue this ${last?.kind ?? "chat"} as a chat`
                    : working && last.kind !== "chat"
                      ? `You can continue once the ${last.kind} ends`
                      : "You can ask once the agent has replied"
            }
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            disabled={!thread.continuable}
            rows={2}
          />
          {stop.isError && (
            <p className="note" role="alert" style={{ margin: "0 0 6px" }}>
              Not stopped: {stop.error.message}
            </p>
          )}
          {send.isError && (
            <p className="note" role="alert" style={{ margin: "0 0 6px" }}>
              Not sent: {send.error.message}
            </p>
          )}
          <div className="aw-box-row">
            <button type="button" className="aw-ico" aria-label="Attach" disabled>
              <Plus aria-hidden />
            </button>
            <span className="flex-1" />
            <ChoicePicker
              harness={thread.harness}
              info={info}
              folderDefault={folderDefault}
              value={choice}
              onChange={setChoice}
              disabled={!thread.continuable && !working}
            />
            {working && !queues ? (
              <button
                type="button"
                className="aw-send"
                aria-label="Stop"
                title="Stop the agent"
                disabled={stop.isPending || last?.status === "stopping"}
                onClick={() => stop.mutate()}
              >
                <Square aria-hidden />
              </button>
            ) : (
              <button
                type="button"
                className="aw-send"
                aria-label={queues ? "Queue" : "Send"}
                title={queues ? "Sends when this turn ends" : undefined}
                disabled={!ready || !text.trim()}
                onClick={submit}
              >
                <ArrowUp aria-hidden />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
