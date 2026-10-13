import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../../api/client";
import {
  type AgentSettings,
  type ChoiceKind,
  type Effort,
  type FolderChoice,
  type FolderSettings,
  type HarnessInfo,
  useAgentSettings,
  useHarnesses,
  useResetAgentSettings,
  useSetAgentDefaults,
  useSetFolderChoice,
} from "../../api/queries";
import { HarnessLogo } from "../../components/HarnessLogo";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import {
  effortLabel,
  effortsOf,
  findModel,
  harnessLabel,
  modelId,
  modelName,
} from "../../lib/agents";
import { useActions } from "../../shell/actions";

const CHATS: { kind: ChoiceKind; name: string; about: string }[] = [
  { kind: "general", name: "General", about: "Questions about the whole desk" },
  { kind: "strategies", name: "Strategies", about: "Chats in a strategy's folder" },
  { kind: "scripts", name: "Scripts", about: "Chats in a script's folder" },
];
const BACKGROUND: { kind: ChoiceKind; name: string; about: string }[] = [
  { kind: "reviews", name: "Reviews", about: "Judge one strategy's ledger after costs" },
  { kind: "debriefs", name: "Debriefs", about: "Each trading day, after the close" },
];
type DefaultsBody = Parameters<ReturnType<typeof useSetAgentDefaults>["mutate"]>[0];

const DEFAULT = "__default";
const OTHER = "__other";
const MAX_RUNS = 500;

const failed = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** Why the settings didn't load. A bare 404 means the server predates them (ADR 40). */
function loadFailed(error: unknown) {
  if (error instanceof ApiError && error.status === 404 && error.detail === "Not Found") {
    return (
      <>
        Agent settings didn't load: this <code>openticker-serve</code> doesn't have them yet.
        Restart it from this version.
      </>
    );
  }
  return `Agent settings didn't load: ${failed(error)}`;
}

const Pending = ({ width }: { width: number }) => (
  <span className="skeleton" style={{ width }} aria-hidden />
);

/**
 * How the user's coding agent runs (ADR 40), set here and read by every run
 * from then on: the agent, each folder's model and effort, the background
 * runs' spend cap and time limit, and runs a day. Laid out like System
 * Settings: grouped rows that open in place. What isn't set comes from the
 * server's environment.
 */
export function AgentsSection() {
  const settings = useAgentSettings();
  const harnessQuery = useHarnesses();
  const harnesses = harnessQuery.data?.harnesses ?? [];
  const harnessesLoaded = harnessQuery.isSuccess;
  const defaults = useSetAgentDefaults();
  const reset = useResetAgentSettings();
  const { notify } = useActions();
  const [open, setOpen] = useState<ChoiceKind | null>(null);
  const data = settings.data;
  const harness = data ? (data.harness ?? data.harness_env) : undefined;
  const runs = data ? (data.runs_per_day ?? data.runs_per_day_env) : undefined;

  const saveDefaults = (body: DefaultsBody) =>
    defaults.mutate(body, {
      onSuccess: () => notify("Saved"),
      onError: (error) => notify(`Not saved: ${failed(error)}`),
    });

  return (
    <section className="tile" id="agents" aria-labelledby="agents-title">
      <div className="settings-head">
        <h2 id="agents-title">Agents</h2>
      </div>
      <p className="note settings-note">
        The coding agent OpenTicker runs for you, on this machine, signed in as you. Changes save as
        you make them.
      </p>
      {settings.isError ? (
        <div className="st-error" role="alert">
          <span className="st-error-text">{loadFailed(settings.error)}</span>
          <button
            type="button"
            className="btn"
            data-size="sm"
            disabled={settings.isFetching}
            onClick={() => settings.refetch()}
          >
            Try again
          </button>
        </div>
      ) : (
        <AgentsForm
          data={data}
          harness={harness}
          runs={runs}
          harnesses={harnesses}
          harnessesLoaded={harnessesLoaded}
          pending={defaults.isPending}
          open={open}
          setOpen={setOpen}
          saveDefaults={saveDefaults}
        />
      )}

      <div className="st-foot">
        <p className="note">
          Anything not set here comes from <code>OPENTICKER_AGENT_*</code> in the server's
          environment, then from the agent's own default.
        </p>
        <button
          type="button"
          className="btn"
          data-size="sm"
          disabled={!data || reset.isPending}
          onClick={() =>
            reset.mutate(undefined, {
              onSuccess: () => notify("Agent settings reset to the environment"),
              onError: (error) => notify(`Not reset: ${failed(error)}`),
            })
          }
        >
          Reset to environment
        </button>
      </div>
    </section>
  );
}

function AgentsForm({
  data,
  harness,
  runs,
  harnesses,
  harnessesLoaded,
  pending,
  open,
  setOpen,
  saveDefaults,
}: {
  data: AgentSettings | undefined;
  harness: string | null | undefined;
  runs: number | null | undefined;
  harnesses: HarnessInfo[];
  harnessesLoaded: boolean;
  pending: boolean;
  open: ChoiceKind | null;
  setOpen: (kind: ChoiceKind | null) => void;
  saveDefaults: (body: DefaultsBody) => void;
}) {
  return (
    <>
      <div className="st-group">
        <h3 className="st-gh">Agent</h3>
        <fieldset className="st-harness" aria-label="Agent">
          {(["claude", "codex"] as const).map((name) => {
            const info = harnesses.find((h) => h.harness === name);
            return (
              <label key={name} className="st-hp">
                <input
                  type="radio"
                  name="agent-harness"
                  className="sr-only"
                  checked={harness === name}
                  disabled={!data || (info !== undefined && !info.installed) || pending}
                  onChange={() => saveDefaults({ harness: name })}
                />
                <HarnessLogo harness={name} size={32} />
                <span>
                  <b>{harnessLabel(name)}</b>
                  <span>{harnessesLoaded ? installState(info) : <Pending width={96} />}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
        <p className="st-gn">
          Used for every folder unless a folder's own setting picks the other.
        </p>
      </div>

      <div className="st-group">
        <h3 className="st-gh">Chats</h3>
        <div className="st-list">
          {CHATS.map((row) => (
            <FolderRow
              key={row.kind}
              {...row}
              data={data}
              harnesses={harnesses}
              open={open === row.kind}
              onToggle={() => setOpen(open === row.kind ? null : row.kind)}
            />
          ))}
        </div>
        <p className="st-gn">
          Where a chat starts. You can change the model and effort in any chat.
        </p>
      </div>

      <div className="st-group">
        <h3 className="st-gh">Background runs</h3>
        <div className="st-list">
          {BACKGROUND.map((row) => (
            <FolderRow
              key={row.kind}
              {...row}
              background
              data={data}
              harnesses={harnesses}
              open={open === row.kind}
              onToggle={() => setOpen(open === row.kind ? null : row.kind)}
            />
          ))}
          <div className="st-item">
            <div className="st-row">
              <span className="st-lbl">
                <b>Runs a day</b>
                <span className="st-about">
                  Reviews and debriefs together. More wait until tomorrow.
                </span>
              </span>
              <span className="st-stepper">
                <button
                  type="button"
                  aria-label="Fewer runs a day"
                  disabled={runs == null || runs <= 1 || pending}
                  onClick={() => runs && saveDefaults({ runs_per_day: runs - 1 })}
                >
                  −
                </button>
                <span className="st-count" aria-live="polite">
                  {runs ?? <Pending width={20} />}
                </span>
                <button
                  type="button"
                  aria-label="More runs a day"
                  disabled={runs == null || runs >= MAX_RUNS || pending}
                  onClick={() => runs && saveDefaults({ runs_per_day: runs + 1 })}
                >
                  +
                </button>
              </span>
            </div>
          </div>
        </div>
        <p className="st-gn">These run with nobody watching, so they always use these settings.</p>
      </div>
    </>
  );
}

function installState(info: HarnessInfo | undefined) {
  if (!info) return "Not reported by the server";
  if (!info.installed) return "Not installed on this machine";
  return (
    <>
      <span className="st-ok">Ready</span>
      {info.version ? ` · ${info.version}` : ""}
    </>
  );
}

function FolderRow({
  kind,
  name,
  about,
  background,
  data,
  harnesses,
  open,
  onToggle,
}: {
  kind: ChoiceKind;
  name: string;
  about: string;
  background?: boolean;
  data: AgentSettings | undefined;
  harnesses: HarnessInfo[];
  open: boolean;
  onToggle: () => void;
}) {
  const folder = data?.folders.find((f) => f.kind === kind);
  const fieldsId = `agents-${kind}`;
  return (
    <div className="st-item">
      <button
        type="button"
        className="st-row"
        aria-expanded={open && folder !== undefined}
        aria-controls={fieldsId}
        disabled={!folder}
        onClick={onToggle}
      >
        <span className="st-lbl">
          <b>{name}</b>
          <span className="st-about">{about}</span>
        </span>
        <span className="st-sum">
          {folder ? (
            summary(
              folder,
              harnesses.find((h) => h.harness === folder.resolved.harness),
              background,
            )
          ) : (
            <Pending width={88} />
          )}
        </span>
        <ChevronRight className="st-chev" aria-hidden />
      </button>
      {open && folder && (
        <FolderFields
          id={fieldsId}
          folder={folder}
          name={name}
          background={background}
          info={harnesses.find((h) => h.harness === folder.resolved.harness)}
        />
      )}
    </div>
  );
}

function summary(folder: FolderSettings, info: HarnessInfo | undefined, background?: boolean) {
  const r = folder.resolved;
  const cap = background && r.max_budget_usd != null ? ` · $${r.max_budget_usd.toFixed(2)}` : "";
  const model = r.model ? modelName(info?.models, r.model) : null;
  if (!model && !r.effort) return `Agent's default${cap}`;
  return (
    <>
      {model ?? "Default model"} · {effortLabel(r.effort)}
      {cap}
    </>
  );
}

function FolderFields({
  id,
  folder,
  name,
  background,
  info,
}: {
  id: string;
  folder: FolderSettings;
  name: string;
  background?: boolean;
  info: HarnessInfo | undefined;
}) {
  const save = useSetFolderChoice();
  const { notify } = useActions();
  const [typingOther, setTypingOther] = useState(false);
  const stored = folder.stored;
  const resolved = folder.resolved;
  const claude = resolved.harness === "claude";
  const envModel = folder.env.harness === resolved.harness ? folder.env.model : null;

  const change = (patch: Partial<FolderChoice>) =>
    save.mutate(
      {
        kind: folder.kind,
        choice: {
          harness: stored.harness,
          model: stored.model,
          effort: stored.effort,
          max_budget_usd: stored.max_budget_usd,
          timeout_minutes: stored.timeout_minutes,
          ...patch,
        },
      },
      {
        onSuccess: () => notify("Saved"),
        onError: (error) => notify(`Not saved: ${failed(error)}`),
      },
    );

  const models = info?.models ?? [];
  const listed = findModel(models, stored.model);
  // The levels are the model's own: the one picked, else the one the agent runs.
  const running = stored.model
    ? listed
    : (findModel(models, resolved.model) ?? info?.default_model ?? undefined);
  const levels = effortsOf(info, running);
  const pickModel = (model: string | null) => {
    const next = model ? findModel(models, model) : (info?.default_model ?? undefined);
    const keeps = stored.effort !== null && effortsOf(info, next).includes(stored.effort);
    change(keeps ? { model } : { model, effort: null });
  };
  const unlisted = stored.model !== null && listed === undefined;
  const typing = typingOther || unlisted || (info?.free_text_model ?? false);
  const fallback = info?.default_model;
  return (
    <div className="st-fields" id={id}>
      <span className="st-fl">Model</span>
      <div className="st-model">
        {models.length > 0 && (
          <Select
            label={`${name} model`}
            value={typing ? OTHER : (listed?.id ?? DEFAULT)}
            options={[
              {
                value: DEFAULT,
                label: "Default",
                hint: envModel ? modelName(models, envModel) : (fallback?.resolves_to ?? undefined),
                detail: envModel
                  ? "Set by OPENTICKER_AGENT_MODEL"
                  : (fallback?.about ?? "The agent's own default"),
              },
              ...models.map((model) => ({
                value: model.id,
                label: model.name,
                hint: modelId(model),
                detail: model.about || undefined,
              })),
              { value: OTHER, label: "Other model…", detail: "Type any name the agent takes" },
            ]}
            onChange={(value) => {
              setTypingOther(value === OTHER);
              if (value !== OTHER) pickModel(value === DEFAULT ? null : value);
            }}
          />
        )}
        {typing && (
          <CommitInput
            label={`${name} model name`}
            value={unlisted ? (stored.model ?? "") : ""}
            placeholder={envModel ?? "Model name, as the agent takes it"}
            onCommit={(text) => pickModel(text.trim() || null)}
          />
        )}
        {listed && (
          <span className="st-model-about">
            {listed.about && `${listed.about.replace(/\.$/, "")}.`}
            {listed.resolves_to && (
              <>
                {" "}
                Runs <code>{listed.resolves_to}</code> today, and newer releases as the agent ships
                them.
              </>
            )}
          </span>
        )}
      </div>
      <span className="st-fl">Effort</span>
      <div>
        {levels.length > 0 ? (
          <Segmented<Effort | typeof DEFAULT>
            label={`${name} effort`}
            value={stored.effort && levels.includes(stored.effort) ? stored.effort : DEFAULT}
            segments={[
              {
                value: DEFAULT,
                label: running?.default_effort
                  ? `Auto (${effortLabel(running.default_effort)})`
                  : "Auto",
              },
              ...levels.map((level) => ({ value: level, label: effortLabel(level) })),
            ]}
            onChange={(value) => change({ effort: value === DEFAULT ? null : value })}
          />
        ) : (
          <span className="st-model-about">
            {running ? `${running.name} has no effort setting.` : "Pick a model to set its effort."}
          </span>
        )}
      </div>
      {background && claude && (
        <>
          <span className="st-fl">Spend cap a run</span>
          <CommitInput
            label={`${name} spend cap a run, in dollars`}
            value={stored.max_budget_usd == null ? "" : String(stored.max_budget_usd)}
            placeholder={
              folder.env.max_budget_usd == null ? "No cap" : `$${folder.env.max_budget_usd}`
            }
            onCommit={(text) => {
              const value = text.replace("$", "").trim();
              change({ max_budget_usd: value ? Number(value) : null });
            }}
          />
          <span className="st-hint">
            Claude Code stops the run when it reaches this. Empty: from the environment.
          </span>
        </>
      )}
      {background && (
        <>
          <span className="st-fl">Time limit</span>
          <CommitInput
            label={`${name} time limit, in minutes`}
            value={stored.timeout_minutes == null ? "" : String(stored.timeout_minutes)}
            placeholder={`${folder.env.timeout_minutes ?? 15} min`}
            onCommit={(text) => {
              const value = text.replace(/min/i, "").trim();
              change({ timeout_minutes: value ? Number.parseInt(value, 10) : null });
            }}
          />
        </>
      )}
    </div>
  );
}

/** A text box that saves when it loses focus or on Enter, and only when changed. */
function CommitInput({
  label,
  value,
  placeholder,
  onCommit,
}: {
  label: string;
  value: string;
  placeholder: string;
  onCommit: (text: string) => void;
}) {
  const [text, setText] = useState(value);
  const commit = () => {
    if (text.trim() !== value) onCommit(text);
  };
  return (
    <input
      className="input tabular"
      aria-label={label}
      value={text}
      placeholder={placeholder}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
}
