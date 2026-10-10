import { X } from "lucide-react";
import { Link } from "react-router";
import { type BrainGraph, useBrainNote } from "../../api/queries";
import { Markdown } from "../../components/Markdown";
import { failureOf, TableFailed } from "../../components/TableStates";
import {
  heldText,
  KIND_LABEL,
  recordHref,
  statusLabel,
  statusTone,
  wikiHref,
} from "../../lib/brain";
import { istDate, sourceLabel } from "../../lib/format";

type Point = BrainGraph["notes"][number];
type Head = { note_id: string; kind: Point["kind"]; title: string; status?: string | null };

const MADE_BY_SERVER: Partial<Record<Point["kind"], string>> = {
  strategy:
    "OpenTicker keeps this note for the strategy. Days, lessons and proposals about it link here.",
  symbol: "OpenTicker keeps this note for the symbol. Strategies that trade it link here.",
};

/** The selected note, beside the graph: its text, then what it links to and what links to it. */
export function NoteSheet({ point, onClose }: { point: Point | null; onClose: () => void }) {
  return (
    <aside className="brain-sheet" data-open={point !== null} aria-label="Selected note">
      {point && (
        <>
          <button
            type="button"
            className="brain-sheet-close"
            aria-label="Close note"
            onClick={onClose}
          >
            <X size={15} aria-hidden />
          </button>
          <NoteBody point={point} />
        </>
      )}
    </aside>
  );
}

function NoteBody({ point }: { point: Point }) {
  const query = useBrainNote(point.note_id);
  const note = query.data;
  const failure = failureOf(query);
  const record = recordHref(point.kind, point.key);
  return (
    <div className="brain-sheet-body">
      <div className="brain-sheet-meta">
        {point.status && (
          <span className="badge" data-tone={statusTone(point.status)}>
            {statusLabel(point.status)}
          </span>
        )}
        <span>
          {KIND_LABEL[point.kind]}
          {note && note.written_by !== "server" && (
            <>
              {" "}
              · {sourceLabel(note.updated_source)} · {istDate(note.updated_at, { time: true })}
            </>
          )}
        </span>
      </div>
      <h2>{point.title}</h2>
      {note?.debrief && <p className="brain-headline">{note.debrief.headline}</p>}
      {note?.kind === "lesson" && (
        <p className="brain-sheet-step">
          {heldText(note.checks, note.held)}
          {note.next_step && <> · {note.next_step}</>}
        </p>
      )}
      {failure ? (
        <TableFailed what="The note" failure={failure} />
      ) : !note ? (
        <p className="note" role="status">
          Loading the note…
        </p>
      ) : (
        <>
          {note.body ? (
            <Markdown text={note.body} linkTo={wikiHref(note.links_out)} />
          ) : (
            <p className="note">{MADE_BY_SERVER[note.kind] ?? "Nothing written yet."}</p>
          )}
          {note.your_note && (
            <section>
              <h3 className="brain-sheet-h">Your note</h3>
              <Markdown text={note.your_note} linkTo={wikiHref(note.links_out)} />
            </section>
          )}
          <Heads title="Links" heads={note.links_out} />
          <Heads title="Linked from" heads={note.backlinks} />
          {note.facts.length > 0 && (
            <section>
              <h3 className="brain-sheet-h">Facts behind it</h3>
              <p className="brain-facts">
                {note.facts.map((f) => (
                  <code key={`${f.kind}:${f.key}`}>
                    {f.kind} {f.key}
                  </code>
                ))}
              </p>
            </section>
          )}
          {record && (
            <Link to={record.href} className="btn" data-size="sm">
              {record.label}
            </Link>
          )}
        </>
      )}
    </div>
  );
}

function Heads({ title, heads }: { title: string; heads: Head[] }) {
  if (heads.length === 0) return null;
  return (
    <section>
      <h3 className="brain-sheet-h">
        {title} <span className="count">{heads.length}</span>
      </h3>
      <ul className="brain-heads">
        {heads.map((h) => (
          <li key={h.note_id}>
            <Link to={`#${h.note_id}`} className="wikilink">
              {h.title}
            </Link>
            <span className="note">
              {KIND_LABEL[h.kind]}
              {h.status && ` · ${statusLabel(h.status)}`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
