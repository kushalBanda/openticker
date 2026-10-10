import { useLearning } from "../../api/queries";

const share = (value: number) => `${Math.round(value * 100)}%`;

/**
 * Whether the brain is being read, over the last 30 days: how many designs
 * and reviews that could have cited a lesson did, the checks still owed,
 * and how many lessons held. Counted by the server from what was recorded.
 */
export function LearningLine() {
  const learning = useLearning(30);
  if (learning.isError) {
    return (
      <p className="note brain-learning" data-testid="learning-line">
        Learning didn't load
      </p>
    );
  }
  const l = learning.data;
  if (!l) return null;
  const could = l.designs + l.reviews;
  const cited = l.designs_citing + l.reviews_citing;

  return (
    <p className="note brain-learning" data-testid="learning-line">
      <span title="Designs and reviews made while a lesson applied, that recorded relying on one">
        {l.cite_share === null || l.cite_share === undefined ? (
          "No design or review yet with a lesson to cite"
        ) : (
          <>
            Lessons cited in <b>{share(l.cite_share)}</b> of designs and reviews ({cited} of {could}
            )
          </>
        )}
      </span>
      <span title="Runs and orders that ended in the last 30 days, still waiting on a check">
        {l.checks_owed === 0 ? "no checks owed" : `${l.checks_owed} checks owed`}
      </span>
      {l.lessons_checked > 0 && (
        <span title="Lessons checked in the last 30 days that held more often than not">
          {l.lessons_held} of {l.lessons_checked} lessons held
        </span>
      )}
      <span>30 days</span>
    </p>
  );
}
