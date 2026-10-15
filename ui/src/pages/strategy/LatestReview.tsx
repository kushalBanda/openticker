import type { Schemas } from "../../api/client";
import { useManager, useStartReview } from "../../api/queries";
import { Markdown } from "../../components/Markdown";
import { istDate } from "../../lib/format";
import { askedBy, reviewedWhen, type Strategy, verdictBadge } from "../../lib/strategies";
import { useActions } from "../../shell/actions";

type Job = Schemas["AgentJobResult"];

const day = (at: string) => istDate(at);

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

export function LatestReview({
  id,
  summary,
  reviews,
}: {
  id: string;
  summary: Strategy | undefined;
  reviews: Job[] | undefined;
}) {
  const latest = summary?.last_review;
  const managerOn = useManager().data?.enabled === true;
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
        <span className="flex-1" />
        <span className="note">{reviewedWhen(managerOn)}</span>
      </div>
    </div>
  );
}
