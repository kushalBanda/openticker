import { Link } from "react-router";
import { KIND_LABEL, noteHref } from "../../lib/brain";

/** Notes a page links to, or that link to it, each to its own page. */
export function NoteHeads({
  heads,
  empty,
}: {
  heads: { note_id: string; kind: string; key: string; title: string }[];
  empty: string;
}) {
  if (heads.length === 0) return <p className="note">{empty}</p>;
  return (
    <ul className="brain-heads">
      {heads.map((h) => (
        <li key={h.note_id}>
          <Link to={noteHref(h)} className="wikilink">
            {h.title}
          </Link>
          <span className="note">{KIND_LABEL[h.kind as keyof typeof KIND_LABEL]}</span>
        </li>
      ))}
    </ul>
  );
}
