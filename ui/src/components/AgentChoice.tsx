import { useState } from "react";
import {
  type Effort,
  type FolderChoice,
  type FolderSettings,
  type HarnessInfo,
  useSetFolderChoice,
} from "../api/queries";
import { effortLabel, effortsOf, findModel, modelId, modelName } from "../lib/agents";
import { useActions } from "../shell/actions";
import { Segmented } from "./Segmented";
import { Select } from "./Select";

// How one folder's runs are made (ADR 40): its model, effort, spend cap and
// time limit. Settings › Agents shows one per folder; the Manager page its own.

const DEFAULT = "__default";
const OTHER = "__other";

const failed = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function installState(info: HarnessInfo | undefined) {
  if (!info) return "Not reported by the server";
  if (!info.installed) return "Not installed on this machine";
  return (
    <>
      <span className="st-ok">Ready</span>
      {info.version ? ` · ${info.version}` : ""}
    </>
  );
}

export function summary(
  folder: FolderSettings,
  info: HarnessInfo | undefined,
  background?: boolean,
) {
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

export function FolderFields({
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
export function CommitInput({
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
