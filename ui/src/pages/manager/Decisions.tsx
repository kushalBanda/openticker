import { Link } from "react-router";
import { useAgentThread } from "../../api/queries";
import { Markdown } from "../../components/Markdown";
import { failureOf, TableEmpty, TableFailed, TableSkeleton } from "../../components/TableStates";
import { istMinute } from "../../lib/format";
import { isWake, type WakeFacts, wakeFacts, wakeLabel } from "../../lib/manager";

/** What the manager decided on a day: each turn of its day's thread, newest first. */
export function Decisions({ threadId, past }: { threadId: string | null; past?: boolean }) {
  const day = past ? "that day" : "today";
  const thread = useAgentThread(threadId);
  const failure = failureOf(thread);
  const turns = [...(thread.data?.turns ?? [])].reverse();
  return (
    <div className="tile" data-flush="true">
      <div className="tile-head">
        <h2>Decisions {day}</h2>
        <span className="flex-1" />
        {threadId && (
          <Link to={`/agents/${threadId}`}>Open {past ? "its" : "today's"} thread ›</Link>
        )}
      </div>
      {threadId === null ? (
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
        <ol className="mgr-decisions">
          {turns.map(({ job }) => {
            const at = new Date(job.started_at ?? job.created_at);
            const wake = isWake(job.trigger);
            const failed = job.status === "ended" && job.end_reason !== "finished";
            return (
              <li key={job.job_id}>
                <time dateTime={at.toISOString()}>{istMinute(at)}</time>
                <div>
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
                  {job.status !== "ended" ? (
                    <p className="note">Working on it…</p>
                  ) : failed ? (
                    <p className="note">{job.end_detail}</p>
                  ) : job.summary ? (
                    <Markdown className="mgr-said" text={job.summary} />
                  ) : (
                    <p className="note">It gave no answer.</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
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
