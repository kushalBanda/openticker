import { ArrowUp, Folder, SquareTerminal, X } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import {
  type Access,
  type HarnessInfo,
  useAgentSettings,
  useHarnesses,
  useScripts,
  useStartChat,
  useStrategies,
} from "../../api/queries";
import { HarnessLogo } from "../../components/HarnessLogo";
import { harnessLabel } from "../../lib/agents";
import { choiceKind, type Suggestion, suggestions } from "../../lib/threads";
import { AccessPicker } from "./AccessPicker";
import { type Choice, ChoicePicker } from "./ChoicePicker";
import { useFolderDefault } from "./Composer";

const GENERAL = { folder: "general", subject: null, where: "General" } as const;
type Where = Pick<Suggestion, "folder" | "subject" | "where">;

/** A new chat: what to ask, where it's filed, with which agent, model and
 * effort. Three questions from the desk start it off. */
export function NewChat() {
  const start = useStartChat();
  const navigate = useNavigate();
  // Seeded by "Start a new chat with this context" in a chat that can't go on.
  const seed = (useLocation().state as { seed?: Suggestion } | null)?.seed;
  const [text, setText] = useState(seed?.text ?? "");
  const [picked, setPicked] = useState<HarnessInfo["harness"] | null>(null);
  const [choice, setChoice] = useState<Choice>({ model: null, effort: null });
  const [where, setWhere] = useState<Where>(seed ?? GENERAL);
  const [access, setAccess] = useState<Access>("trade");
  const strategies = useStrategies().data?.strategies;
  const scripts = useScripts().data?.scripts;
  const offered = strategies && scripts ? suggestions(strategies, scripts) : [];
  const folder = useAgentSettings().data?.folders.find((f) => f.kind === choiceKind(where.folder));
  const installed = (useHarnesses().data?.harnesses ?? []).filter((h) => h.installed);
  const harness = picked ?? folder?.resolved.harness ?? "claude";
  const { info, loading, folderDefault } = useFolderDefault(harness, where.folder);
  const other = installed.find((h) => h.harness !== harness);

  const submit = () => {
    const message = text.trim();
    if (!message || start.isPending) return;
    start.mutate(
      {
        message,
        ...choice,
        harness: picked,
        folder: where.folder,
        subject: where.subject,
        access,
      },
      { onSuccess: (thread) => navigate(`/agents/${thread.thread_id}`) },
    );
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <>
      <div className="aw-scroll scroll">
        <div className="aw-empty">
          <SquareTerminal className="aw-glyph" aria-hidden />
          <h2>What should we look into?</h2>
          <p className="note">Your own Claude Code or Codex, with your desk's tools.</p>
          {offered.length > 0 && (
            <ul className="aw-sugg" aria-label="Suggestions">
              {offered.map((s) => (
                <li key={s.text}>
                  <button
                    type="button"
                    onClick={() => {
                      setText(s.text);
                      setWhere(s);
                    }}
                  >
                    <span>{s.text}</span>
                    <span className="aw-ctx">{s.where}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="aw-dock">
        <div className="aw-composer">
          <div className="aw-chips">
            {where.folder === "general" ? (
              <span className="aw-chip">
                <Folder aria-hidden />
                General
              </span>
            ) : (
              <button
                type="button"
                className="aw-chip"
                aria-label={`In ${where.where}: file it in General instead`}
                onClick={() => setWhere(GENERAL)}
              >
                <Folder aria-hidden />
                {where.where}
                <X aria-hidden />
              </button>
            )}
            {other ? (
              <button
                type="button"
                className="aw-chip"
                title={`Use ${harnessLabel(other.harness)} instead`}
                onClick={() => {
                  setPicked(other.harness);
                  setChoice({ model: null, effort: null });
                }}
              >
                <HarnessLogo harness={harness} size={14} />
                {harnessLabel(harness)}
              </button>
            ) : (
              <span className="aw-chip">
                <HarnessLogo harness={harness} size={14} />
                {harnessLabel(harness)}
              </span>
            )}
          </div>
          <div className="aw-box">
            <textarea
              aria-label="Message"
              placeholder="Ask about your desk, a strategy, a day"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              rows={2}
            />
            {start.isError && (
              <p className="note" role="alert" style={{ margin: "0 0 6px" }}>
                Not sent: {start.error.message}
              </p>
            )}
            <div className="aw-box-row">
              <AccessPicker value={access} onChange={setAccess} />
              <span className="flex-1" />
              <ChoicePicker
                harness={harness}
                info={info}
                loading={loading}
                folderDefault={folderDefault}
                value={choice}
                onChange={setChoice}
              />
              <button
                type="button"
                className="aw-send"
                aria-label="Send"
                disabled={start.isPending || !text.trim()}
                onClick={submit}
              >
                <ArrowUp aria-hidden />
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
