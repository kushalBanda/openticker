import { Link } from "react-router";
import { type ManagerDay, useManagerDay } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { loaded, StatCard } from "../../components/StatCard";
import { failureOf, TableEmpty, TableFailed, TableSkeleton } from "../../components/TableStates";
import { dayTitle } from "../../lib/brain";
import { direction, MISSING, rupees } from "../../lib/format";
import { changeText, lineLabel, market, setByLabel, tableOrder } from "../../lib/manager";
import { Decisions } from "./Decisions";
import { HowItRan } from "./HowItRan";
import { Plan } from "./Plan";
import { Split } from "./Split";

type DayLine = ManagerDay["lines"][number];

function Money({ value, crossed }: { value: number | null | undefined; crossed?: boolean }) {
  if (value == null) return <span className="missing">{MISSING}</span>;
  return (
    <span className={crossed ? "down" : direction(value)}>{rupees(value, { sign: true })}</span>
  );
}

const columns: Column<DayLine>[] = [
  {
    key: "what",
    head: "Strategy",
    align: "left",
    cell: (l) => <span className="inst">{lineLabel(l)}</span>,
    // The story of its numbers that day, oldest first.
    sub: (l) =>
      l.changes.length > 0 ? (
        <span className="mgr-chg">
          {l.changes.map((change, i) => (
            <span key={change.at} data-after={change.after_close}>
              {changeText(change, l.changes[i - 1])}
            </span>
          ))}
        </span>
      ) : l.key === "desk" ? (
        "Includes what was still open"
      ) : null,
  },
  {
    key: "capital",
    head: "Capital",
    align: "right",
    cell: (l) => (l.stood ? rupees(l.capital, { decimals: 0 }) : MISSING),
  },
  {
    key: "stop",
    head: "Stop it at",
    align: "right",
    cell: (l) => (l.stood && l.stop != null ? rupees(l.stop, { decimals: 0 }) : MISSING),
  },
  {
    key: "market",
    head: "Market",
    align: "right",
    cell: (l) => <Money value={l.figure && market(l.figure)} />,
  },
  {
    key: "charges",
    head: "Charges",
    align: "right",
    cell: (l) => <Money value={l.figure && -l.figure.charges} />,
  },
  {
    key: "day",
    head: "That day",
    align: "right",
    cell: (l) => <Money value={l.figure?.net} crossed={l.crossed} />,
    sub: (l) => (l.crossed ? "past its stop" : null),
  },
  {
    key: "by",
    head: "Set by",
    align: "left",
    cell: (l) =>
      l.stood ? (
        <span className="badge" data-tone={l.set_by === "you" ? "accent" : undefined}>
          {setByLabel(l.set_by)}
        </span>
      ) : null,
  },
];

/** A past day of the manager's, read only, as it closed (ADR 43). */
export function PastDay({ day }: { day: string }) {
  const found = useManagerDay(day);
  const data = found.data;
  const failure = failureOf(found);
  const stood = data?.lines.filter((l) => l.stood) ?? [];
  const given = stood.reduce((sum, l) => sum + (l.key === "desk" ? 0 : (l.capital ?? 0)), 0);
  const stops = stood.filter((l) => l.stop != null);
  const crossed = stops.filter((l) => l.crossed).length;
  return (
    <section className="mgr-day" aria-labelledby="mgr-day-title">
      <div className="mgr-day-head">
        <h2 id="mgr-day-title">{dayTitle(day)}</h2>
        <p>
          {found.isError
            ? `This day didn't load: ${found.error.message}`
            : !data
              ? "Loading the day…"
              : data.ran
                ? "As it closed: what stood at 15:30, and what changed it."
                : "The manager was off this day. The desk's money is from the P&L record."}
        </p>
      </div>
      <div className="stats">
        <StatCard
          label="That day"
          value={loaded(found, (d) =>
            d.desk ? rupees(d.desk.net, { sign: true }) : "Not recorded",
          )}
          tone={direction(data?.desk?.net)}
          note={data?.desk ? <Split figure={data.desk} /> : data && "No P&L was recorded that day"}
        />
        <StatCard
          label="Given to strategies"
          value={loaded(found, () => (stood.length ? rupees(given, { decimals: 0 }) : "None"))}
          note={data && (stood.length ? "at the close" : "No numbers stood")}
        />
        <StatCard
          label="Looks"
          value={loaded(found, (d) => (d.ran ? d.looks : "None"))}
          note={data && (data.ran ? `$${data.cost_usd.toFixed(2)} spent` : "It wasn't on")}
        />
        <StatCard
          label="Stops crossed"
          value={loaded(found, () => (stops.length ? `${crossed} of ${stops.length}` : "None"))}
          tone={crossed ? "down" : undefined}
          note={data && (stops.length ? "at the close" : "No stops stood")}
        />
      </div>
      <div className="tile" data-flush="true">
        <div className="tile-head">
          <h2>Its numbers</h2>
          <span className="flex-1" />
          <span className="note">As they stood at the close. Read only.</span>
        </div>
        {failure ? (
          <TableFailed what="This day" failure={failure} />
        ) : !data ? (
          <TableSkeleton label="Loading that day's numbers" />
        ) : data.lines.length === 0 ? (
          <TableEmpty>
            No numbers that day. Each strategy's own limits still acted; its trades are in the
            brain's day record.
          </TableEmpty>
        ) : (
          <div className="mgr-lines">
            <DataTable
              label="The manager's numbers that day"
              columns={columns}
              rows={tableOrder(data.lines)}
              rowKey={(l) => l.key}
            />
          </div>
        )}
      </div>
      {data && (
        <div className="mgr-row">
          <Decisions threadId={data.thread_ids.at(-1) ?? null} past />
          <div className="mgr-side">
            {data.ran && <HowItRan day={data} />}
            <Plan
              plan={data.plan}
              title="The plan"
              empty={data.ran ? "It set no plan that day." : "No plan: it wasn't on."}
            >
              <div className="mgr-brain-link">
                <span className="muted">{data.debrief ? "Debriefed" : "Not debriefed"}</span>
                <Link to={`/brain/days/${day}`}>The day in the brain ›</Link>
              </div>
            </Plan>
          </div>
        </div>
      )}
    </section>
  );
}
