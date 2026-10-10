import { lazy, Suspense, useState } from "react";
import { ApiError } from "../../api/client";
import { type BrainNote, useEditUserNote, useFreshBrainNote } from "../../api/queries";
import { Markdown } from "../../components/Markdown";
import { pageHref } from "../../lib/brain";
import { istDate, sourceLabel } from "../../lib/format";

// CodeMirror loads with the first editor opened, not with the page.
const MarkdownEditor = lazy(() =>
  import("./MarkdownEditor").then((m) => ({ default: m.MarkdownEditor })),
);

interface Editing {
  text: string;
  from: { version: number; text: string }; // the note as editing began
}

/**
 * The user's own note on a note. Saved against the version editing began
 * from: when someone else changed the user's note meanwhile, both texts
 * show and the user picks. A change to the agent's part alone isn't a
 * conflict, and saves over it.
 */
export function NoteEditor({ note }: { note: BrainNote }) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const [theirs, setTheirs] = useState<BrainNote | null>(null);
  const save = useEditUserNote();
  const fresh = useFreshBrainNote();
  const linkTo = pageHref([...note.links_out, ...note.backlinks]);

  const begin = () => {
    const text = note.your_note ?? "";
    setEditing({ text, from: { version: note.version, text } });
    setTheirs(null);
  };

  const write = (text: string, version: number, started: string) =>
    save.mutate(
      { id: note.note_id, text, version },
      {
        onSuccess: () => {
          setEditing(null);
          setTheirs(null);
        },
        onError: async (error) => {
          if (!(error instanceof ApiError && error.status === 409)) return;
          const now = await fresh(note.note_id);
          if ((now.your_note ?? "") === started) {
            write(text, now.version, started); // only the agent's part moved
          } else {
            setTheirs(now);
          }
        },
      },
    );

  if (editing === null) {
    return (
      <section className="tile" aria-labelledby="your-note">
        <div className="brain-tile-head">
          <h2 id="your-note" className="tile-title">
            Your note
          </h2>
          <button type="button" className="btn" data-size="sm" onClick={begin}>
            {note.your_note ? "Edit" : "Add a note"}
          </button>
        </div>
        {note.your_note ? (
          <>
            <Markdown text={note.your_note} linkTo={linkTo} />
            {note.your_note_at && (
              <p className="note brain-by">
                {note.your_note_source && <>{sourceLabel(note.your_note_source)} · </>}
                {istDate(note.your_note_at, { time: true })}
              </p>
            )}
          </>
        ) : (
          <p className="note">
            Yours alone: agents read it, and a debrief written again leaves it as it is.
          </p>
        )}
      </section>
    );
  }

  return (
    <section className="tile" aria-labelledby="your-note">
      <div className="brain-tile-head">
        <h2 id="your-note" className="tile-title">
          Your note
        </h2>
      </div>
      {theirs && (
        <div className="brain-conflict" role="alert">
          <p>
            <strong>Your note changed while you were editing.</strong> This is what's saved now;
            yours is below. Keep one.
          </p>
          {theirs.your_note ? (
            <Markdown text={theirs.your_note} linkTo={linkTo} />
          ) : (
            <p className="note">Now empty.</p>
          )}
          <div className="brain-actions">
            <button
              type="button"
              className="btn"
              data-size="sm"
              onClick={() => {
                setEditing(null);
                setTheirs(null);
              }}
            >
              Keep what's saved
            </button>
          </div>
        </div>
      )}
      <Suspense fallback={<p className="note">Loading the editor…</p>}>
        <MarkdownEditor
          value={editing.text}
          onChange={(text) => setEditing({ ...editing, text })}
          label="Your note, in markdown"
        />
      </Suspense>
      {save.isError && !(save.error instanceof ApiError && save.error.status === 409) && (
        <p className="note brain-error" role="alert">
          Not saved: {save.error.message}
        </p>
      )}
      <div className="brain-actions">
        <button
          type="button"
          className="btn"
          data-variant="primary"
          data-size="sm"
          disabled={save.isPending}
          onClick={() =>
            theirs
              ? write(editing.text, theirs.version, theirs.your_note ?? "")
              : write(editing.text, editing.from.version, editing.from.text)
          }
        >
          {theirs ? "Save mine instead" : save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          className="btn"
          data-size="sm"
          onClick={() => {
            setEditing(null);
            setTheirs(null);
          }}
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
