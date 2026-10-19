import { ChevronRight } from "lucide-react";
import { useState } from "react";
import {
  type ChoiceKind,
  type FolderSettings,
  type HarnessInfo,
  type Manager,
  useAgentSettings,
  useAgentThread,
  useHarnesses,
  useSetManager,
} from "../../api/queries";
import { CommitInput, FolderFields, installState } from "../../components/AgentChoice";
import { HarnessLogo } from "../../components/HarnessLogo";
import { Tile } from "../../components/Tile";
import { effortLabel, effortsOf, findModel, harnessLabel, modelName } from "../../lib/agents";
import { effortLevel, nextLook, nowDoing, railLooks, spent } from "../../lib/manager";
import { tokens } from "../../lib/threads";
import { useActions } from "../../shell/actions";
import { useServerNow } from "../../stream/StreamProvider";
import { DayRail } from "./DayRail";

const TIERS: { kind: ChoiceKind; tier: "decisive" | "check"; name: string; about: string }[] = [
  {
    kind: "manager",
    tier: "decisive",
    name: "Decisive looks",
    about: "The plan, the close, a breakage, a crossed line, Look now",
  },
  {
    kind: "manager-checks",
    tier: "check",
    name: "Check-ins",
    about: "The time it set, the hourly look",
  },
];

const usd = (value: number | null | undefined) => (value == null ? null : `$${value.toFixed(2)}`);

/**
 * How the manager runs (ADR 41, 42): its next look, today's looks on the
 * session, the two choices its looks run on (each opens its settings here,
 * the same as Settings › Agents), and what today's looks used.
 */
export function HowItRuns({ manager }: { manager: Manager }) {
  const settings = useAgentSettings();
  const harnesses = useHarnesses().data?.harnesses ?? [];
  const thread = useAgentThread(manager.thread_id);
  const switchManager = useSetManager();
  const serverNow = useServerNow();
  const { notify } = useActions();
  const [open, setOpen] = useState<ChoiceKind | null>(null);

  const folders = settings.data?.folders ?? [];
  const decisive = folders.find((f) => f.kind === "manager");
  const harness = decisive?.resolved.harness ?? null;
  const info = harnesses.find((h) => h.harness === harness);
  const turns = thread.data?.turns ?? [];
  const looking = nowDoing(manager.enabled, turns, null, () => "");
  const next = nextLook(
    manager.enabled,
    manager.next_wake_at,
    manager.next_wake_reason,
    serverNow(),
  );
  const { looks, offUntil } = railLooks(turns);
  const last = turns.findLast((t) => t.job.status === "ended")?.job;
  const today = spent(turns);
  const name = (model: string) => modelName(info?.models, model);

  return (
    <Tile
      title="How it runs"
      actions={
        <span className="badge" data-tone={manager.enabled ? "accent" : undefined}>
          {manager.enabled ? "On" : "Off"}
        </span>
      }
      flush
      className="mgr-run"
      testId="how-it-runs"
    >
      <div className="mgr-run-next" role="status">
        <span className="mgr-run-label">{looking.tone ? "Now" : "Next look"}</span>
        <span className="mgr-run-when">{looking.tone ? "Looking" : next.when}</span>
        <span className="mgr-run-why">{looking.tone ? looking.text : next.why}</span>
      </div>

      <DayRail looks={looks} offUntil={offUntil} name={name} />

      {settings.isError ? (
        <p className="error-line mgr-run-error">
          Its settings didn't load: {settings.error.message}
        </p>
      ) : (
        <div className="mgr-run-tiers">
          {TIERS.map(({ kind, tier, name: label, about }) => {
            const folder = folders.find((f) => f.kind === kind);
            const id = `mgr-run-${kind}`;
            return (
              <div key={kind} className="mgr-run-item">
                <button
                  type="button"
                  className="mgr-run-tier"
                  data-tier={tier}
                  aria-expanded={open === kind}
                  aria-controls={id}
                  disabled={!folder}
                  onClick={() => setOpen((was) => (was === kind ? null : kind))}
                >
                  <span className="mgr-run-mark" aria-hidden />
                  <span className="mgr-run-text">
                    <b>{label}</b>
                    <span>{about}</span>
                  </span>
                  {folder ? <Choice folder={folder} info={info} /> : <span />}
                  <ChevronRight className="mgr-run-chev" aria-hidden />
                </button>
                {open === kind && folder && (
                  <FolderFields
                    id={id}
                    folder={folder}
                    name={`Manager: ${label.toLowerCase()}`}
                    background
                    info={info}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <dl className="mgr-run-use">
        <div>
          <dt>Today</dt>
          <dd>{usd(today.usd) ?? (turns.length ? "—" : "$0.00")}</dd>
        </div>
        <div>
          <dt>Looks</dt>
          <dd>
            {manager.wakes_today}
            <span className="mgr-run-of">of</span>
            <CommitInput
              key={manager.wakes_per_day}
              label="Looks a day"
              value={String(manager.wakes_per_day)}
              placeholder="40"
              onCommit={(text) => {
                const wakes = Number.parseInt(text, 10);
                switchManager
                  .mutateAsync({ enabled: manager.enabled, wakes_per_day: wakes })
                  .then(() => notify(`It takes at most ${wakes} looks a day.`))
                  .catch((error: unknown) =>
                    notify(`Not saved: ${error instanceof Error ? error.message : error}`),
                  );
              }}
            />
          </dd>
        </div>
        <div>
          <dt>Last look</dt>
          <dd>{last ? (usd(last.cost_usd) ?? "—") : "None"}</dd>
          {last && (
            <dd className="mgr-run-sub">
              {(last.input_tokens ?? 0) + (last.output_tokens ?? 0) > 0
                ? `${tokens((last.input_tokens ?? 0) + (last.output_tokens ?? 0))} tokens`
                : "No tokens reported"}
            </dd>
          )}
        </div>
      </dl>

      <p className="mgr-run-foot">
        {harness ? (
          <>
            <HarnessLogo harness={harness} size={12} /> {harnessLabel(harness)}:{" "}
            {installState(info)}.{" "}
          </>
        ) : null}
        Both choices run in one conversation a day. A retry runs like the look it repeats; check-ins
        left unset run as the decisive looks. A change applies from the next look.
      </p>
    </Tile>
  );
}

/** A tier's model and its effort as a gauge over the model's own levels. */
function Choice({ folder, info }: { folder: FolderSettings; info: HarnessInfo | undefined }) {
  const run = folder.resolved;
  const model = run.model ? findModel(info?.models ?? [], run.model) : info?.default_model;
  const shown = run.model ? modelName(info?.models, run.model) : (model?.name ?? "Default");
  const level = effortLevel(run.effort, effortsOf(info, model ?? undefined));
  return (
    <span className="mgr-run-model">
      <span className="mgr-run-name">{shown}</span>
      <span
        className="mgr-run-effort"
        data-level={level}
        role="img"
        aria-label={`Effort ${run.effort ? effortLabel(run.effort).toLowerCase() : "auto"}`}
      >
        <i />
        <i />
        <i />
        <i />
        <i />
        <em>{run.effort ? effortLabel(run.effort) : "Auto"}</em>
      </span>
    </span>
  );
}
