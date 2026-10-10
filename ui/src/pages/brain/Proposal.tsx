import { useState } from "react";
import { Link, useParams } from "react-router";
import { type BrainNote, useBrainNote, useDecideProposal } from "../../api/queries";
import { CopyLine } from "../../components/CopyLine";
import { Markdown } from "../../components/Markdown";
import { Page } from "../../components/Page";
import { failureOf, TableFailed } from "../../components/TableStates";
import { heldText, noteHref, pageHref, statusLabel, statusTone } from "../../lib/brain";
import { istDate, sourceLabel } from "../../lib/format";
import { MiniGraph } from "./MiniGraph";
import { NoteEditor } from "./NoteEditor";
import { NoteHeads } from "./NoteHeads";

/** One proposal: the change, why, what could make it wrong, and the user's decision. */
export function Proposal() {
  const { id = "" } = useParams();
  const query = useBrainNote(id);
  const note = query.data;
  const proposal = note?.proposal;
  const failure = failureOf(query);
  const linkTo = note ? pageHref([...note.links_out, ...note.backlinks]) : undefined;

  return (
    <Page
      title={note?.title ?? "Proposal"}
      back={{ to: "/brain/proposals", label: "Proposals" }}
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
          <TableFailed what="The proposal" failure={failure} />
        </div>
      ) : !note || !proposal ? (
        <p className="note" role="status">
          Loading the proposal…
        </p>
      ) : (
        <div className="brain-day">
          <p className="note brain-by brain-day-by">
            Raised {istDate(note.created_at, { time: true })} · {sourceLabel(note.updated_source)}
          </p>
          <div className="overview-grid">
            <div className="flex flex-col gap-6">
              <section className="tile" aria-labelledby="change">
                <h2 id="change" className="tile-title">
                  The change
                </h2>
                <dl className="brain-change">
                  <dt>Strategy</dt>
                  <dd>
                    {note.strategy_id && proposal.strategy_name ? (
                      <Link to={`/strategies/${note.strategy_id}`} className="wikilink">
                        {proposal.strategy_name}
                      </Link>
                    ) : (
                      "A deleted strategy"
                    )}
                  </dd>
                  <dt>Change one thing</dt>
                  <dd>{proposal.change}</dd>
                </dl>
                <h3 className="brain-sheet-h">Why</h3>
                <Markdown text={note.body} linkTo={linkTo} />
                {proposal.based_on.length > 0 && (
                  <ul className="brain-checks">
                    {proposal.based_on.map((l) => (
                      <li key={l.note_id}>
                        <span
                          className="badge"
                          data-tone={l.status ? statusTone(l.status) : undefined}
                        >
                          {l.status ? statusLabel(l.status) : "Lesson"}
                        </span>
                        <div>
                          <Link to={noteHref(l)} className="wikilink">
                            {l.title}
                          </Link>
                          <p className="note">{heldText(l.checks, l.held)} since written</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <h3 className="brain-sheet-h">What could make this wrong</h3>
                <p className="brain-text">{proposal.wrong_if}</p>
              </section>

              <Decision note={note} />
              <NoteEditor note={note} />
            </div>

            <aside className="flex flex-col gap-6">
              <MiniGraph note={note} />
              <section className="tile" aria-labelledby="earlier">
                <h2 id="earlier" className="tile-title">
                  Earlier on this strategy
                </h2>
                {proposal.earlier.length === 0 ? (
                  <p className="note">No other proposals for this strategy.</p>
                ) : (
                  <ul className="brain-uses">
                    {proposal.earlier.map((p) => (
                      <li key={p.note_id}>
                        <span
                          className="badge"
                          data-tone={p.status ? statusTone(p.status) : undefined}
                        >
                          {p.status ? statusLabel(p.status) : ""}
                        </span>{" "}
                        <Link to={noteHref(p)} className="wikilink">
                          {p.title}
                        </Link>
                        <span className="note">
                          {istDate(p.updated_at)}
                          {p.reason && <> · “{p.reason}”</>}
                        </span>
                      </li>
                    ))}
                  </ul>
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

/** Accept (and copy the request), put off, or reject with a reason; once final, what was decided. */
function Decision({ note }: { note: BrainNote }) {
  const [reason, setReason] = useState("");
  const decide = useDecideProposal();
  const proposal = note.proposal;
  if (!proposal) return null;
  const decided = proposal.decided_at && (
    <>
      {proposal.decided_source && <>{sourceLabel(proposal.decided_source)} · </>}
      {istDate(proposal.decided_at, { time: true })}
    </>
  );

  if (note.status === "accepted") {
    return (
      <section className="tile" aria-labelledby="decision">
        <h2 id="decision" className="tile-title">
          Accepted
        </h2>
        <p className="note">{decided}</p>
        <p className="brain-text">
          Accepting changed nothing by itself. Paste this into your agent; it changes the strategy
          between runs, never while one is running.
        </p>
        <CopyLine text={proposal.request} label="Copy the request" />
      </section>
    );
  }
  if (note.status === "rejected") {
    return (
      <section className="tile" aria-labelledby="decision">
        <h2 id="decision" className="tile-title">
          Rejected
        </h2>
        <p className="note">{decided}</p>
        <p className="brain-text">“{note.reason}”</p>
        <p className="note">
          Agents read this reason before proposing something similar for this strategy.
        </p>
      </section>
    );
  }

  // Copied on the click itself, while the browser still counts it as the user's.
  const accept = () => {
    navigator.clipboard?.writeText(proposal.request).catch(() => undefined);
    decide.mutate({ id: note.note_id, decision: "accept" });
  };

  return (
    <section className="tile" aria-labelledby="decision">
      <h2 id="decision" className="tile-title">
        Decide
      </h2>
      {note.status === "later" && <p className="note">Put off {decided}.</p>}
      <p className="brain-text">
        Accepting doesn't change the strategy by itself. It gives you this request to paste into
        your agent; the strategy changes between runs, never while one is running.
      </p>
      <CopyLine text={proposal.request} label="Copy the request" />
      <div className="brain-actions">
        <button
          type="button"
          className="btn"
          data-variant="primary"
          data-size="sm"
          disabled={decide.isPending}
          onClick={accept}
        >
          Accept and copy
        </button>
        {note.status !== "later" && (
          <button
            type="button"
            className="btn"
            data-size="sm"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ id: note.note_id, decision: "later" })}
          >
            Later
          </button>
        )}
      </div>
      <form
        className="brain-retire"
        onSubmit={(e) => {
          e.preventDefault();
          if (reason.trim()) decide.mutate({ id: note.note_id, decision: "reject", reason });
        }}
      >
        <label className="label" htmlFor="reject-reason">
          Rejecting instead? Your reason is kept, and agents read it before proposing again.
        </label>
        <textarea
          id="reject-reason"
          className="input brain-reason"
          value={reason}
          maxLength={2000}
          placeholder="e.g. I want to keep full-day theta on expiry; test on a copy first."
          onChange={(e) => setReason(e.target.value)}
        />
        <div className="brain-actions">
          <button
            type="submit"
            className="btn"
            data-size="sm"
            disabled={!reason.trim() || decide.isPending}
          >
            Reject with reason
          </button>
        </div>
      </form>
      {decide.isError && (
        <p className="note brain-error" role="alert">
          Not decided: {decide.error.message}
        </p>
      )}
    </section>
  );
}
