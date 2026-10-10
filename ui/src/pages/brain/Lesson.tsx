import { useState } from "react";
import { Link, useParams } from "react-router";
import {
  type LessonCheck,
  type OwedCheck,
  useBrainNote,
  useLessonOverride,
  useStrategies,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Markdown } from "../../components/Markdown";
import { Page } from "../../components/Page";
import { StatCard } from "../../components/StatCard";
import { failureOf, TableEmpty, TableFailed } from "../../components/TableStates";
import {
  dayTitle,
  heldText,
  OUTCOME,
  pageHref,
  statusLabel,
  statusTone,
  subjectText,
} from "../../lib/brain";
import { istDate, sourceLabel } from "../../lib/format";
import { MiniGraph } from "./MiniGraph";
import { NoteEditor } from "./NoteEditor";
import { NoteHeads } from "./NoteHeads";

const PURPOSE: Record<string, string> = {
  design: "Design",
  review: "Review",
  debrief: "Debrief",
  answer: "Answer",
};

/** The trading date a check's run or order ended on, as the day page's key. */
function dayOf(at: string | null | undefined): string | null {
  if (!at) return null;
  return at.slice(0, 10); // returned exchange-local, so its date is the trading date
}

function DayLink({ at }: { at: string | null | undefined }) {
  const day = dayOf(at);
  if (!day) return <span className="missing">—</span>;
  return (
    <Link to={`/brain/days/${day}`} className="row-link">
      {dayTitle(day)}
    </Link>
  );
}

/** One lesson: what it says, how often it held since it was written, and who relied on it. */
export function Lesson() {
  const { id = "" } = useParams();
  const query = useBrainNote(id);
  const strategies = useStrategies();
  const names = new Map(
    (strategies.data?.strategies ?? []).map((s) => [s.strategy_id, s.name] as const),
  );
  const note = query.data;
  const lesson = note?.lesson;
  const failure = failureOf(query);
  const share =
    note?.checks && note.held !== null && note.held !== undefined
      ? Math.round((note.held / note.checks) * 100)
      : null;

  const checkColumns: Column<LessonCheck>[] = [
    { key: "day", head: "Day", align: "left", cell: (c) => <DayLink at={c.ended_at} /> },
    {
      key: "subject",
      head: "Run or order",
      align: "left",
      cell: (c) => subjectText(c, names),
      sub: (c) => (c.before_reset ? "Before the paper account was reset" : null),
    },
    { key: "observed", head: "Observed", align: "left", wrap: true, cell: (c) => c.observed ?? "" },
    { key: "why", head: "Why", align: "left", wrap: true, cell: (c) => c.why },
    {
      key: "outcome",
      head: "Held?",
      align: "left",
      cell: (c) => (
        <span className="badge" data-tone={OUTCOME[c.outcome]?.tone}>
          {OUTCOME[c.outcome]?.label ?? c.outcome}
        </span>
      ),
      sub: (c) => sourceLabel(c.checked_source),
    },
  ];

  const owedColumns: Column<OwedCheck>[] = [
    { key: "day", head: "Day", align: "left", cell: (o) => <DayLink at={o.ended_at} /> },
    {
      key: "subject",
      head: "Run or order",
      align: "left",
      cell: (o) => subjectText(o, names),
    },
  ];

  return (
    <Page
      title={note?.title ?? "Lesson"}
      back={{ to: "/brain/lessons", label: "Lessons" }}
      badges={
        note?.status && (
          <span className="badge" data-tone={statusTone(note.status)}>
            {statusLabel(note.status)}
          </span>
        )
      }
      actions={
        note && (
          <Link to={`/brain#${note.note_id}`} className="btn" data-size="sm">
            Show in graph
          </Link>
        )
      }
    >
      {failure ? (
        <div className="tile">
          <TableFailed what="The lesson" failure={failure} />
        </div>
      ) : !note || !lesson ? (
        <p className="note" role="status">
          Loading the lesson…
        </p>
      ) : (
        <div className="brain-day">
          <p className="note brain-by brain-day-by">
            Written {istDate(note.created_at)} · {sourceLabel(note.updated_source)} · applies to{" "}
            {note.applies_to?.length
              ? note.applies_to.map((s) => names.get(s) ?? s).join(", ")
              : "the whole desk"}
          </p>
          <div className="stats">
            <StatCard
              label="Held since written"
              testId="lesson-held"
              value={note.checks ? `${note.held} of ${note.checks}` : "Not checked yet"}
              note={share !== null ? `${share}% of the checks that counted` : undefined}
            />
            <StatCard
              label="Owed checks"
              testId="lesson-owed"
              value={lesson.owed.length}
              note="Ended runs and orders it applies to"
            />
            <StatCard
              label="Used"
              value={lesson.used}
              note={usesNote(lesson.uses.map((u) => u.purpose))}
            />
            <StatCard
              label="Next step"
              testId="lesson-next"
              value={
                <span className="brain-step">
                  {note.next_step ?? heldText(note.checks, note.held)}
                </span>
              }
            />
          </div>

          <Override note={note} />

          <section className="tile" aria-labelledby="lesson-text">
            <h2 id="lesson-text" className="tile-title">
              The lesson
            </h2>
            <Markdown text={note.body} linkTo={pageHref([...note.links_out, ...note.backlinks])} />
          </section>

          <section className="tile" data-flush="true" aria-labelledby="checks">
            <div className="tile-head">
              <h2 id="checks">Checks since it was written</h2>
              <span className="count">{lesson.checks.length}</span>
            </div>
            {lesson.checks.length === 0 ? (
              <TableEmpty>
                No checks yet. Each ended run or order it applies to is owed one; the debrief
                answers them.
              </TableEmpty>
            ) : (
              <DataTable
                label="Checks since it was written"
                columns={checkColumns}
                rows={lesson.checks}
                rowKey={(c) => c.run_id ?? c.order_id ?? ""}
              />
            )}
            <p className="note brain-table-note">
              Each check is judged by the agent that gave it, from the figure it observed.
              OpenTicker decides which runs and orders count and when the status moves.
            </p>
          </section>

          <div className="overview-grid">
            <div className="flex flex-col gap-6">
              <section className="tile" data-flush="true" aria-labelledby="owed">
                <div className="tile-head">
                  <h2 id="owed">Owed checks</h2>
                  <span className="count">{lesson.owed.length}</span>
                </div>
                {note.status === "retired" ? (
                  <TableEmpty>Retired lessons aren't owed checks.</TableEmpty>
                ) : lesson.owed.length === 0 ? (
                  <TableEmpty>
                    Nothing owed: every ended run and order it applies to is checked.
                  </TableEmpty>
                ) : (
                  <DataTable
                    label="Owed checks"
                    columns={owedColumns}
                    rows={lesson.owed}
                    rowKey={(o) => o.run_id ?? o.order_id ?? ""}
                  />
                )}
              </section>
              <NoteEditor note={note} />
            </div>

            <aside className="flex flex-col gap-6">
              <MiniGraph note={note} />
              <section className="tile" aria-labelledby="uses">
                <h2 id="uses" className="tile-title">
                  Used by
                </h2>
                {lesson.uses.length === 0 ? (
                  <p className="note">No agent has recorded relying on it yet.</p>
                ) : (
                  <ul className="brain-uses">
                    {lesson.uses.map((u) => (
                      <li key={`${u.used_at}-${u.used_by}`}>
                        <b>
                          {PURPOSE[u.purpose] ?? u.purpose}
                          {u.strategy_id && <> · {names.get(u.strategy_id) ?? u.strategy_id}</>}
                        </b>
                        <span className="note">
                          {istDate(u.used_at)} · {sourceLabel(u.used_source)} · {u.how}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="tile" aria-labelledby="evidence">
                <h2 id="evidence" className="tile-title">
                  What it came from
                </h2>
                {lesson.evidence.length === 0 ? (
                  <p className="note">No evidence was cited when it was written.</p>
                ) : (
                  <p className="brain-facts">
                    {lesson.evidence.map((e) =>
                      e.startsWith("day:") ? (
                        <Link key={e} to={`/brain/days/${e.slice(4)}`} className="wikilink">
                          {dayTitle(e.slice(4))}
                        </Link>
                      ) : (
                        <code key={e}>{e.replace(":", " ")}</code>
                      ),
                    )}
                  </p>
                )}
              </section>
              <section className="tile" aria-labelledby="links">
                <h2 id="links" className="tile-title">
                  Links
                </h2>
                <NoteHeads heads={note.links_out} empty="Links to nothing yet." />
                <h3 className="brain-sheet-h">Linked from</h3>
                <NoteHeads heads={note.backlinks} empty="Nothing links here yet." />
              </section>
            </aside>
          </div>
        </div>
      )}
    </Page>
  );
}

function usesNote(purposes: string[]): string | undefined {
  if (purposes.length === 0) return undefined;
  const counts = new Map<string, number>();
  for (const p of purposes) counts.set(p, (counts.get(p) ?? 0) + 1);
  return [...counts]
    .map(([p, n]) => `${n} ${(PURPOSE[p] ?? p).toLowerCase()}${n === 1 ? "" : "s"}`)
    .join(", ");
}

/** Retire, reinstate, or hand the status back to the checks: the user's say, with a reason to retire. */
function Override({ note }: { note: NonNullable<ReturnType<typeof useBrainNote>["data"]> }) {
  const [retiring, setRetiring] = useState(false);
  const [reason, setReason] = useState("");
  const override = useLessonOverride();
  const lesson = note.lesson;
  if (!lesson) return null;
  const set = (value: "retired" | "reinstated" | "none", why?: string) =>
    override.mutate(
      { id: note.note_id, override: value, reason: why },
      { onSuccess: () => setRetiring(false) },
    );

  return (
    <section className="tile brain-override" aria-labelledby="override">
      <div className="brain-tile-head">
        <h2 id="override" className="tile-title">
          {lesson.override === "retired"
            ? "Retired by you"
            : lesson.override === "reinstated"
              ? "Reinstated by you"
              : note.status === "retired"
                ? "Retired by its checks"
                : "Status from its checks"}
        </h2>
        {!retiring && (
          <div className="brain-actions brain-actions-inline">
            {note.status === "retired" ? (
              <button
                type="button"
                className="btn"
                data-size="sm"
                disabled={override.isPending}
                onClick={() => set("reinstated")}
              >
                Reinstate
              </button>
            ) : (
              <button
                type="button"
                className="btn"
                data-size="sm"
                onClick={() => setRetiring(true)}
              >
                Retire…
              </button>
            )}
            {lesson.override && (
              <button
                type="button"
                className="btn"
                data-size="sm"
                data-variant="ghost"
                disabled={override.isPending}
                onClick={() => set("none")}
              >
                Let the checks decide
              </button>
            )}
          </div>
        )}
      </div>
      <p className="note">
        {lesson.override && lesson.override_at ? (
          <>
            {lesson.override_source && <>{sourceLabel(lesson.override_source)} · </>}
            {istDate(lesson.override_at, { time: true })}
            {lesson.override_reason && <> · “{lesson.override_reason}”</>}
            {lesson.override === "reinstated" &&
              ". Its checks decide again; it won't be retired by them until 5 more checks."}
          </>
        ) : (
          "Tested at 3 checks with 60% held, a rule at 10 with 70%; retired at 5 below 40%. Agents don't rely on a retired lesson."
        )}
      </p>
      {retiring && (
        <form
          className="brain-retire"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) set("retired", reason);
          }}
        >
          <label className="label" htmlFor="retire-reason">
            Why retire it? Agents read the reason.
          </label>
          <input
            id="retire-reason"
            className="input"
            value={reason}
            maxLength={2000}
            onChange={(e) => setReason(e.target.value)}
            // biome-ignore lint/a11y/noAutofocus: the form opens on the user's own click
            autoFocus
          />
          <div className="brain-actions">
            <button
              type="submit"
              className="btn"
              data-variant="primary"
              data-size="sm"
              disabled={!reason.trim() || override.isPending}
            >
              Retire
            </button>
            <button type="button" className="btn" data-size="sm" onClick={() => setRetiring(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {override.isError && (
        <p className="note brain-error" role="alert">
          Not changed: {override.error.message}
        </p>
      )}
    </section>
  );
}
