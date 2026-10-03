import { useState } from "react";
import type { Schemas } from "../../api/client";
import { useReviewSchedule, useStartReview } from "../../api/queries";
import { Dialog } from "../../components/Dialog";
import { Markdown } from "../../components/Markdown";
import { istDate, rupees } from "../../lib/format";
import { askedBy, type Strategy, verdictBadge } from "../../lib/strategies";
import { useActions } from "../../shell/actions";

type Job = Schemas["AgentJobResult"];
type ReviewSchedule = Schemas["ReviewScheduleResult"];

const day = (at: string) => istDate(at);

/** "every 1d · after 20 runs · on a ₹5,000 drawdown" */
export function scheduleText(schedule: ReviewSchedule | null | undefined): string | null {
  if (!schedule) return null;
  return [
    schedule.every && `every ${schedule.every}`,
    schedule.after_runs && `after ${schedule.after_runs} runs`,
    schedule.drawdown && `on a ${rupees(schedule.drawdown, { decimals: 0 })} drawdown`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function VerdictBadge({ verdict }: { verdict: Job["verdict"] }) {
  const badge = verdictBadge(verdict);
  if (!badge) return null;
  return (
    <span className="badge" data-tone={badge.tone}>
      {badge.label}
    </span>
  );
}

/** Review now, and whether it is already under way. */
export function ReviewNow({
  id,
  reviews,
  variant,
}: {
  id: string;
  reviews: Job[] | undefined;
  variant?: "primary";
}) {
  const start = useStartReview();
  const { notify } = useActions();
  const open = reviews?.find((j) => j.status !== "ended");
  return (
    <button
      type="button"
      className="btn"
      data-variant={variant}
      disabled={start.isPending || open !== undefined}
      onClick={async () => {
        try {
          await start.mutateAsync(id);
          notify("Review asked for: your coding agent reads the ledger and writes the verdict.");
        } catch (error) {
          notify(error instanceof Error ? error.message : String(error));
        }
      }}
    >
      {open ? (open.status === "pending" ? "Review waiting…" : "Reviewing…") : "Review now"}
    </button>
  );
}

export function ReviewScheduleButton({
  id,
  current,
}: {
  id: string;
  current: ReviewSchedule | null | undefined;
}) {
  const [open, setOpen] = useState(false);
  const [every, setEvery] = useState(current?.every ?? "");
  const [afterRuns, setAfterRuns] = useState(current?.after_runs?.toString() ?? "");
  const [drawdown, setDrawdown] = useState(current?.drawdown?.toString() ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useReviewSchedule();
  const { notify } = useActions();

  const submit = async (off: boolean) => {
    setError(null);
    const schedule = off
      ? null
      : {
          every: every.trim() || null,
          after_runs: afterRuns.trim() ? Number(afterRuns) : null,
          drawdown: drawdown.trim() ? Number(drawdown) : null,
        };
    if (schedule && !schedule.every && !schedule.after_runs && !schedule.drawdown) {
      setError("Set at least one: every, after runs or a drawdown.");
      return;
    }
    try {
      await save.mutateAsync({ strategyId: id, schedule });
      setOpen(false);
      notify(off ? "Reviewed only when asked from now on." : "Review schedule saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <button type="button" className="btn" data-variant="ghost" onClick={() => setOpen(true)}>
        Review schedule…
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Review schedule">
        <p className="note" style={{ margin: 0 }}>
          Your coding agent reviews it without being asked when any of these is met. Each review is
          one agent job, within the day's cap.
        </p>
        <div className="fields">
          <label className="field">
            <span className="label">Every</span>
            <input
              className="input"
              value={every}
              placeholder="1d"
              onChange={(e) => setEvery(e.target.value)}
              aria-describedby="every-help"
            />
          </label>
          <label className="field">
            <span className="label">After runs</span>
            <input
              className="input"
              type="number"
              min={1}
              value={afterRuns}
              placeholder="20"
              onChange={(e) => setAfterRuns(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="label">Drawdown ₹</span>
            <input
              className="input"
              type="number"
              min={1}
              value={drawdown}
              placeholder="5000"
              onChange={(e) => setDrawdown(e.target.value)}
            />
          </label>
        </div>
        <p id="every-help" className="note" style={{ margin: 0 }}>
          Every: a number and m, h or d, like 4h or 1d.
        </p>
        {error && (
          <div className="error-line" role="alert">
            {error}
          </div>
        )}
        <div className="flex items-center gap-2">
          {current && (
            <button
              type="button"
              className="btn"
              data-variant="ghost"
              disabled={save.isPending}
              onClick={() => submit(true)}
            >
              Turn off
            </button>
          )}
          <span className="flex-1" />
          <button type="button" className="btn" data-variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="btn"
            data-variant="primary"
            disabled={save.isPending}
            onClick={() => submit(false)}
          >
            Save
          </button>
        </div>
      </Dialog>
    </>
  );
}

export function LatestReview({
  id,
  summary,
  reviews,
  schedule,
}: {
  id: string;
  summary: Strategy | undefined;
  reviews: Job[] | undefined;
  schedule: ReviewSchedule | null | undefined;
}) {
  const latest = summary?.last_review;
  const when = scheduleText(schedule);
  return (
    <div className="tile" data-testid="latest-review">
      <div className="flex items-center gap-2">
        <h2 className="tile-title">Latest review</h2>
        {latest && <VerdictBadge verdict={latest.verdict} />}
        <span className="flex-1" />
        {latest && (
          <span className="note">
            {day(latest.ended_at)} · {latest.harness === "codex" ? "Codex" : "Claude"} ·{" "}
            {askedBy(latest.trigger)}
          </span>
        )}
      </div>
      {latest ? (
        <Markdown text={latest.summary ?? ""} className="review-text" />
      ) : (
        <p className="review-text">
          Not reviewed yet. A review reads the ledger after costs and writes a verdict (keep, change
          one thing, retire) into the strategy's note.
        </p>
      )}
      <div className="flex items-center gap-2">
        <ReviewNow id={id} reviews={reviews} />
        <ReviewScheduleButton key={when ?? "none"} id={id} current={schedule} />
        <span className="flex-1" />
        <span className="note">{when ? `Also reviewed ${when}` : "Reviewed only when asked"}</span>
      </div>
    </div>
  );
}
