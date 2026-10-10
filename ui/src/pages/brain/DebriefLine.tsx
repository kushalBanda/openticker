import { useState } from "react";
import { useDebriefSchedule, useScheduleDebrief, useStartDebrief } from "../../api/queries";
import { Segmented } from "../../components/Segmented";
import { istDate } from "../../lib/format";
import { useActions } from "../../shell/actions";

const TIMES = ["15:45", "16:30", "18:00"] as const;
type At = (typeof TIMES)[number];

/**
 * The daily debrief: off, with a time to turn it on at (the first run), or
 * on, with when it next runs. Either way a debrief can be asked for now.
 */
export function DebriefLine() {
  const schedule = useDebriefSchedule();
  const set = useScheduleDebrief();
  const start = useStartDebrief();
  const { notify } = useActions();
  const [at, setAt] = useState<At>("15:45");
  if (!schedule.data) return null;
  const on = schedule.data.at;

  const now = async () => {
    try {
      const started = await start.mutateAsync(null);
      notify(`${started.job.title} asked for: your coding agent writes it in a few minutes.`);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };
  const writeNow = (
    <button type="button" className="btn" data-size="sm" disabled={start.isPending} onClick={now}>
      Write one now
    </button>
  );

  if (on) {
    return (
      <div className="brain-debrief" data-testid="debrief-line">
        <span>
          Debrief after every close at <b>{on}</b>
          {schedule.data.next_due && <> · next {istDate(schedule.data.next_due, { time: true })}</>}
        </span>
        <div className="brain-actions brain-actions-inline">
          {writeNow}
          <button
            type="button"
            className="btn"
            data-size="sm"
            data-variant="ghost"
            disabled={set.isPending}
            onClick={() => set.mutate(null)}
          >
            Turn off
          </button>
        </div>
      </div>
    );
  }
  return (
    <section className="brain-debrief" data-testid="debrief-line" aria-labelledby="debrief-setup">
      <div>
        <h2 id="debrief-setup" className="brain-debrief-title">
          Daily debrief
        </h2>
        <p className="note">
          After each close your own Claude Code or Codex writes the day up: each trade with its
          reasons and trade-offs, what could have been done better, and whether the lessons held.
          Its key reads the day and writes only the brain; it can't place, change or start anything.
        </p>
      </div>
      <div className="brain-actions brain-actions-inline">
        <Segmented<At>
          label="Debrief time"
          value={at}
          onChange={setAt}
          segments={TIMES.map((t) => ({ value: t, label: t }))}
        />
        <button
          type="button"
          className="btn"
          data-variant="primary"
          data-size="sm"
          disabled={set.isPending}
          onClick={() => set.mutate(at)}
        >
          Turn on
        </button>
        {writeNow}
      </div>
    </section>
  );
}
