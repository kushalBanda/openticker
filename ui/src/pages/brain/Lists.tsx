import { useNavigate } from "react-router";
import { type BrainFound, useBrainSearch, useStrategies } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { TableSkeleton } from "../../components/TableStates";
import { heldText, type NoteKind, noteHref, statusLabel, statusTone } from "../../lib/brain";
import { istDate } from "../../lib/format";

const LIMIT = 100;

const EMPTY: Record<"day" | "lesson" | "proposal", { title: string; text: string }> = {
  day: {
    title: "No days yet",
    text: "A trading day appears here once a note is written about it.",
  },
  lesson: {
    title: "No lessons yet",
    text:
      "Your agent writes them from what the trading showed. Each starts as a hunch and earns " +
      "its status from checks on later runs.",
  },
  proposal: {
    title: "No proposals yet",
    text:
      "An agent raises one when a lesson suggests changing one thing in a strategy. Nothing " +
      "changes until you accept it and ask your agent.",
  },
};

const WRITTEN_BY: Record<string, string> = {
  agent_job: "Agent job",
  person: "You or your agent",
  server: "OpenTicker",
};

const NAME: Record<"day" | "lesson" | "proposal", string> = {
  day: "Days",
  lesson: "Lessons",
  proposal: "Proposals",
};

function Status({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return (
    <span className="badge" data-tone={statusTone(status)}>
      {statusLabel(status)}
    </span>
  );
}

/** One kind of note as a table; a row opens the note in the graph. */
export function NoteList({ kind }: { kind: "day" | "lesson" | "proposal" }) {
  const list = useBrainSearch({ kind, limit: LIMIT });
  const strategies = useStrategies();
  const navigate = useNavigate();
  const names = new Map(strategies.data?.strategies.map((s) => [s.strategy_id, s.name]));
  const strategy = (id: string) => names.get(id) ?? id;

  const updated: Column<BrainFound> = {
    key: "updated",
    head: "Updated",
    cell: (n) => istDate(n.updated_at, { time: true }),
  };
  const columns: Record<NoteKind, Column<BrainFound>[]> = {
    day: [
      { key: "day", head: "Day", align: "left", cell: (n) => n.title },
      {
        key: "by",
        head: "Written by",
        align: "left",
        cell: (n) => WRITTEN_BY[n.written_by] ?? n.written_by,
      },
      updated,
    ],
    lesson: [
      { key: "lesson", head: "Lesson", align: "left", wrap: true, cell: (n) => n.title },
      { key: "status", head: "Status", align: "left", cell: (n) => <Status status={n.status} /> },
      { key: "held", head: "Checks", align: "left", cell: (n) => heldText(n.checks, n.held) },
      {
        key: "scope",
        head: "Applies to",
        align: "left",
        wrap: true,
        cell: (n) =>
          n.applies_to?.length ? n.applies_to.map(strategy).join(", ") : "Every strategy",
      },
      updated,
    ],
    proposal: [
      { key: "proposal", head: "Proposal", align: "left", wrap: true, cell: (n) => n.title },
      { key: "state", head: "State", align: "left", cell: (n) => <Status status={n.status} /> },
      {
        key: "strategy",
        head: "Strategy",
        align: "left",
        cell: (n) => (n.strategy_id ? strategy(n.strategy_id) : ""),
        sub: (n) => n.reason && `Rejected: ${n.reason}`,
      },
      updated,
    ],
    strategy: [],
    symbol: [],
  };

  return (
    <div className="tile" data-flush="true">
      {list.isPending ? (
        <TableSkeleton label={`Loading ${NAME[kind].toLowerCase()}`} rows={3} />
      ) : list.isError ? (
        <div className="empty" role="alert">
          <h2>{NAME[kind]} didn't load</h2>
          <p className="note">{list.error.message}</p>
          <button type="button" className="btn" onClick={() => list.refetch()}>
            Try again
          </button>
        </div>
      ) : list.data.notes.length === 0 ? (
        <div className="empty">
          <h2>{EMPTY[kind].title}</h2>
          <p className="note">{EMPTY[kind].text}</p>
        </div>
      ) : (
        <DataTable
          label={NAME[kind]}
          columns={columns[kind]}
          rows={list.data.notes}
          rowKey={(n) => n.note_id}
          onSelect={(id) => {
            const note = list.data.notes.find((n) => n.note_id === id);
            navigate(note ? noteHref(note) : `/brain#${id}`);
          }}
        />
      )}
    </div>
  );
}
