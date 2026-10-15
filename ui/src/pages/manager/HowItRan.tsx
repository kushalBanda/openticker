import { type ManagerDay, useAgentSettings, useAgentThread, useHarnesses } from "../../api/queries";
import { effortLabel, modelName } from "../../lib/agents";
import { railLooks } from "../../lib/manager";
import { DayRail } from "./DayRail";

/**
 * How a past day ran (ADR 43): its looks on the session, what they ran on,
 * and what they cost. Read only: the choices for the days to come are today's.
 */
export function HowItRan({ day }: { day: ManagerDay }) {
  const thread = useAgentThread(day.thread_ids.at(-1) ?? null);
  const harness = useAgentSettings().data?.folders.find((f) => f.kind === "manager")?.resolved
    .harness;
  const info = useHarnesses().data?.harnesses.find((h) => h.harness === harness);
  const name = (model: string) => modelName(info?.models, model);
  const { looks, offUntil } = railLooks(thread.data?.turns ?? []);
  return (
    <section
      className="tile mgr-run"
      data-flush="true"
      data-testid="how-it-ran"
      aria-labelledby="mgr-ran-title"
    >
      <div className="tile-head">
        <h2 id="mgr-ran-title">How it ran</h2>
      </div>
      <DayRail
        looks={looks}
        offUntil={offUntil}
        name={name}
        label="That day's looks on the session"
        empty="No looks that day"
      />
      <dl className="mgr-ran-used">
        {day.models.map((m) => (
          <div key={`${m.tier}-${m.model}-${m.effort}`} className="mgr-ran-row">
            <dt>{m.tier === "decisive" ? "Decisive looks" : "Check-ins"}</dt>
            <dd>
              {m.model ? name(m.model) : "Its default"} · {effortLabel(m.effort)} × {m.looks}
            </dd>
          </div>
        ))}
        <div className="mgr-ran-row">
          <dt>Spent</dt>
          <dd>${day.cost_usd.toFixed(2)}</dd>
        </div>
      </dl>
      <p className="mgr-run-foot">
        What it ran on that day. The choices for the days ahead are today's.
      </p>
    </section>
  );
}
