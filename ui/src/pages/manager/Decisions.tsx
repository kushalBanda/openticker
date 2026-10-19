import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";
import { useAgentThread } from "../../api/queries";
import { Markdown } from "../../components/Markdown";
import { Scroll } from "../../components/Scroll";
import { failureOf, TableEmpty, TableFailed, TableSkeleton } from "../../components/TableStates";
import { Timeline } from "../../components/Timeline";
import { istMinute } from "../../lib/format";
import { isWake, type WakeFacts, wakeFacts, wakeLabel } from "../../lib/manager";

const FOLDED = "openticker.manager.decisions-folded";

function readFolded(): boolean {
  try {
    return localStorage.getItem(FOLDED) === "1";
  } catch {
    return false;
  }
}

/**
 * What the manager decided on a day, as a panel down the page's right edge
 * (DESIGN.md Side Panel): each turn of its day's thread, newest first, as
 * tall as the page beside it and scrolling on its own. It folds to a strip, and stays
 * folded until opened again.
 */
export function Decisions({
  threadId,
  past,
}: {
  /** The day's thread; null when it didn't run, undefined while the day loads. */
  threadId: string | null | undefined;
  past?: boolean;
}) {
  const day = past ? "that day" : "today";
  const title = `Decisions ${day}`;
  const id = useId();
  const [folded, setFolded] = useState(readFolded);
  const thread = useAgentThread(threadId ?? null);
  const failure = failureOf(thread);
  const turns = [...(thread.data?.turns ?? [])].reverse();
  const fold = (next: boolean) => {
    setFolded(next);
    try {
      localStorage.setItem(FOLDED, next ? "1" : "0");
    } catch {
      // A private window: it folds for this visit only.
    }
  };
  if (folded) {
    return (
      <aside className="mgr-panel" data-folded aria-label={title}>
        <button
          type="button"
          className="mgr-panel-strip"
          aria-label={`Show ${title.toLowerCase()}`}
          aria-expanded={false}
          onClick={() => fold(false)}
        >
          <PanelRightOpen size={16} aria-hidden />
          <span>{title}</span>
          {turns.length > 0 && <b>{turns.length}</b>}
        </button>
      </aside>
    );
  }
  return (
    <aside className="mgr-panel" aria-labelledby={id}>
      <div className="mgr-panel-in">
        <div className="mgr-panel-head">
          <h2 id={id}>{title}</h2>
          {turns.length > 0 && <span className="count">{turns.length}</span>}
          <span className="flex-1" />
          {threadId && (
            <Link to={`/agents/${threadId}`} className="mgr-panel-link">
              Thread ›
            </Link>
          )}
          <button
            type="button"
            className="mgr-panel-fold"
            aria-label={`Hide ${title.toLowerCase()}`}
            aria-expanded
            onClick={() => fold(true)}
          >
            <PanelRightClose size={16} aria-hidden />
          </button>
        </div>
        <Scroll className="mgr-panel-body">
          {threadId === undefined ? (
            <TableSkeleton label={`Loading the decisions of ${day}`} />
          ) : threadId === null ? (
            <TableEmpty>
              {past
                ? "Nothing that day: it didn't run."
                : "Nothing yet today. It plans the day before the open."}
            </TableEmpty>
          ) : failure ? (
            <TableFailed what={`The thread of ${day}`} failure={failure} />
          ) : !thread.data ? (
            <TableSkeleton label={`Loading the decisions of ${day}`} />
          ) : (
            <Timeline
              label={`Decisions ${day}`}
              className="mgr-decisions"
              entries={turns.map(({ job }) => {
                const at = new Date(job.started_at ?? job.created_at);
                const wake = isWake(job.trigger);
                const working = job.status !== "ended";
                const failed = !working && job.end_reason !== "finished";
                return {
                  key: job.job_id,
                  time: istMinute(at),
                  at,
                  tone: failed ? "down" : wake ? undefined : "accent",
                  live: working,
                  body: (
                    <>
                      <div className="mgr-what">
                        <span className="badge" data-tone={wake ? undefined : "accent"}>
                          {wake ? `Woke: ${wakeLabel(job.trigger)}` : "You wrote"}
                        </span>
                        {failed && (
                          <span className="badge" data-tone="down">
                            {job.end_reason}
                          </span>
                        )}
                      </div>
                      {!wake && job.prompt && <p className="mgr-asked">{job.prompt}</p>}
                      {wake && <Told facts={wakeFacts(job.prompt)} />}
                      {working ? (
                        <p className="note">Working on it…</p>
                      ) : failed ? (
                        <p className="note">{job.end_detail}</p>
                      ) : job.summary ? (
                        <Markdown className="mgr-said" text={job.summary} />
                      ) : (
                        <p className="note">It gave no answer.</p>
                      )}
                    </>
                  ),
                };
              })}
            />
          )}
        </Scroll>
      </div>
    </aside>
  );
}

/** What a plan wake was told before it looked: what broke since the last close, and its answer then. */
function Told({ facts }: { facts: WakeFacts | null }) {
  if (!facts) return null;
  return (
    <div className="mgr-told">
      <div className="label">Since the last close{facts.from ? `, ${facts.from}` : ""}</div>
      {facts.since.length === 0 ? (
        <p className="note">Nothing broke.</p>
      ) : (
        <ul>
          {facts.since.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <div className="label">Yesterday's close</div>
      <p className="note">{facts.close ?? "No close answer."}</p>
    </div>
  );
}
