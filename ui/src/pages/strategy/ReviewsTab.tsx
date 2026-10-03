import type { UseQueryResult } from "@tanstack/react-query";
import type { Schemas } from "../../api/client";
import { Markdown } from "../../components/Markdown";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { istDate } from "../../lib/format";
import { askedBy } from "../../lib/strategies";
import { ReviewNow, ReviewScheduleButton, scheduleText, VerdictBadge } from "./LatestReview";

type Jobs = Schemas["AgentJobsResult"];
type Job = Jobs["jobs"][number];

const stamp = (at: string) => istDate(at, { time: true });

function Outcome({ job }: { job: Job }) {
  if (job.status === "pending")
    return (
      <span className="badge" data-tone="accent">
        Waiting
      </span>
    );
  if (job.status !== "ended")
    return (
      <span className="badge" data-tone="accent">
        Reviewing
      </span>
    );
  if (job.end_reason !== "finished")
    return (
      <span className="badge" data-tone="down" title={job.end_detail ?? undefined}>
        {job.end_reason === "timeout" ? "Timed out" : "Failed"}
      </span>
    );
  return <VerdictBadge verdict={job.verdict} />;
}

/** Every review, newest first, with its answer. */
export function ReviewsTab({
  id,
  reviews,
  schedule,
}: {
  id: string;
  reviews: UseQueryResult<Jobs>;
  schedule: Schemas["ReviewScheduleResult"] | null | undefined;
}) {
  const when = scheduleText(schedule);
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>Reviews</h2>
        <span className="note">{when ? `also ${when}` : "only when asked"}</span>
        <span className="flex-1" />
        <ReviewScheduleButton key={when ?? "none"} id={id} current={schedule} />
        <ReviewNow id={id} reviews={reviews.data?.jobs} variant="primary" />
      </div>
      {reviews.isPending ? (
        <TableSkeleton label="Loading reviews" />
      ) : reviews.isError ? (
        <TableEmpty>{`Reviews didn't load: ${reviews.error.message}`}</TableEmpty>
      ) : reviews.data.jobs.length === 0 ? (
        <TableEmpty>
          Not reviewed yet. Review now asks your coding agent to read the ledger and write a verdict
          into the strategy's note.
        </TableEmpty>
      ) : (
        <ol className="review-list" aria-label="Reviews">
          {reviews.data.jobs.map((job) => (
            <li key={job.job_id}>
              <div className="flex items-center gap-2">
                <Outcome job={job} />
                <span className="note">
                  {stamp(job.ended_at ?? job.created_at)} ·{" "}
                  {job.harness === "codex" ? "Codex" : "Claude"} · {askedBy(job.trigger)}
                  {job.cost_usd != null && ` · $${job.cost_usd.toFixed(2)}`}
                </span>
              </div>
              {job.summary && <Markdown text={job.summary} />}
              {!job.summary && job.status === "ended" && job.end_detail && (
                <p className="note">{job.end_detail}</p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
