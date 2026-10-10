import { Link, useParams } from "react-router";
import {
  type DayRecord,
  type DayTrade,
  useBrainNote,
  useDayRecord,
  useStartDebrief,
  useStrategies,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Markdown } from "../../components/Markdown";
import { Page } from "../../components/Page";
import { PlacedBy } from "../../components/PlacedBy";
import { StatCard } from "../../components/StatCard";
import { failureOf, TableEmpty, TableFailed } from "../../components/TableStates";
import { dayTitle, OUTCOME, pageHref, subjectText } from "../../lib/brain";
import {
  direction,
  istDate,
  istMinute,
  MISSING,
  qty,
  rupees,
  signed,
  sourceLabel,
} from "../../lib/format";
import { useActions } from "../../shell/actions";
import { useLive } from "../../stream/StreamProvider";
import { MiniGraph } from "./MiniGraph";
import { NoteEditor } from "./NoteEditor";
import { NoteHeads } from "./NoteHeads";

const STOPS: Record<string, string> = {
  kill: "killed",
  manual: "stopped by hand",
  schedule: "exited on schedule",
  expiry: "exited at expiry",
  combined_stop_loss: "stop loss",
  combined_target: "target",
  profit_lock: "profit lock",
  daily_loss_limit: "daily loss limit",
  tick_stale: "prices lost",
  recovery_failed: "not recovered",
  error: "error",
  legs_closed: "legs closed",
};

function Money({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="missing">{MISSING}</span>;
  return <span className={direction(value)}>{signed(value)}</span>;
}

/** "Sell 10 RELIANCE 09:30 · Buy 10 10:55": a run's or an order's fills that day. */
function fillsText(trade: DayTrade): string {
  const parts = trade.fills.map(
    (f) =>
      `${f.side === "BUY" ? "Buy" : "Sell"} ${qty(f.quantity)} ${f.symbol} ${istMinute(new Date(f.filled_at))}`,
  );
  if (parts.length > 4) return `${parts.slice(0, 3).join(" · ")} · ${parts.length - 3} more fills`;
  return parts.join(" · ") || "No fills that day";
}

const columns: Column<DayTrade>[] = [
  {
    key: "who",
    head: "Strategy or order",
    align: "left",
    cell: (t) =>
      t.run_id ? (
        t.strategy_id ? (
          <Link to={`/strategies/${t.strategy_id}`} className="row-link">
            {t.strategy_name ?? "Deleted strategy"}
          </Link>
        ) : (
          t.strategy_name
        )
      ) : (
        <PlacedBy row={t} />
      ),
    sub: (t) =>
      t.run_id
        ? `Run · ${t.stop_reason ? (STOPS[t.stop_reason] ?? t.stop_reason) : (t.run_status ?? "")}`
        : "Order outside a strategy",
  },
  {
    key: "trade",
    head: "Trade",
    align: "left",
    wrap: true,
    cell: (t) => fillsText(t),
    sub: (t) => (t.why ? `Why: ${t.why}` : null),
  },
  { key: "charges", head: "Charges", cell: (t) => rupees(t.charges) },
  { key: "net", head: "Net", cell: (t) => <Money value={t.net} /> },
  {
    key: "tradeoff",
    head: "Trade-off",
    align: "left",
    wrap: true,
    cell: (t) => t.trade_off || <span className="missing">{t.why ? "" : "Not written"}</span>,
  },
];

/** One trading day: its record after charges and the debrief's account of it. */
export function Day() {
  const { date = "" } = useParams();
  const { status } = useLive();
  const record = useDayRecord(status?.broker, date);
  const note = useBrainNote(record.data?.note_id ?? null);
  const failure = failureOf(record);
  const data = record.data;
  const debrief = note.data?.debrief;
  const net = data?.net_pnl;

  return (
    <Page
      title={note.data?.title ?? dayTitle(date)}
      back={{ to: "/brain/days", label: "Days" }}
      badges={
        data && (
          <span className="badge" data-tone={direction(net)}>
            {net === null || net === undefined
              ? "Net not known yet"
              : `${rupees(net, { sign: true })} after charges`}
          </span>
        )
      }
      actions={
        data && (
          <>
            <WriteDebrief date={date} written={Boolean(debrief)} />
            {data.note_id && (
              <Link to={`/brain#${data.note_id}`} className="btn" data-size="sm">
                Show in graph
              </Link>
            )}
          </>
        )
      }
    >
      {failure ? (
        <div className="tile">
          <TableFailed what="The day" failure={failure} />
        </div>
      ) : (
        <div className="brain-day">
          {debrief && note.data && (
            <p className="note brain-by brain-day-by">
              Debrief · {sourceLabel(note.data.updated_source)} ·{" "}
              {istDate(note.data.updated_at, { time: true })}
              {note.data.your_note_at && (
                <> · your note {istDate(note.data.your_note_at, { time: true })}</>
              )}
            </p>
          )}
          {data?.frozen_at && (
            <p className="brain-frozen" role="note">
              Kept from before the paper account was reset on{" "}
              {istDate(data.frozen_at, { time: true })}: the trade book no longer has these trades.
            </p>
          )}
          <div className="stats">
            <StatCard
              label="Net after charges"
              value={data ? <Money value={net} /> : <span className="skeleton" />}
              note={data?.live ? "Live until the close is recorded" : undefined}
            />
            <StatCard
              label="Realized"
              value={data ? <Money value={data.realized_pnl} /> : <span className="skeleton" />}
            />
            <StatCard
              label="Charges"
              testId="day-charges"
              value={data ? rupees(data.charges) : <span className="skeleton" />}
            />
            <StatCard
              label="Fills"
              testId="day-fills"
              value={data ? qty(data.fills) : <span className="skeleton" />}
            />
          </div>

          <section className="tile" aria-labelledby="happened">
            <h2 id="happened" className="tile-title">
              What happened
            </h2>
            {debrief && note.data ? (
              <>
                <p className="brain-headline">{debrief.headline}</p>
                {note.data.body && (
                  <Markdown
                    text={note.data.body}
                    linkTo={pageHref([...note.data.links_out, ...note.data.backlinks])}
                  />
                )}
              </>
            ) : data ? (
              <p className="note">
                No debrief yet. Ask your agent to debrief {dayTitle(date)}: it reads the day with
                get_day_record and writes it with write_debrief.
              </p>
            ) : (
              <p className="note" role="status">
                Loading the day…
              </p>
            )}
          </section>

          <section className="tile" data-flush="true" aria-labelledby="trades">
            <div className="tile-head">
              <h2 id="trades">Trades and trade-offs</h2>
              {data && <span className="count">{data.trades.length}</span>}
            </div>
            {!data ? (
              <p className="note" style={{ padding: "0 24px 20px" }} role="status">
                Loading the trades…
              </p>
            ) : data.trades.length === 0 ? (
              <TableEmpty>Nothing traded this day.</TableEmpty>
            ) : (
              <DataTable
                label="Trades and trade-offs"
                columns={columns}
                rows={data.trades}
                rowKey={(t) => t.run_id ?? t.order_id ?? ""}
              />
            )}
            {data?.truncated && (
              <TableEmpty>More fills than fit here: the trade book has them all.</TableEmpty>
            )}
          </section>

          <div className="overview-grid">
            <div className="flex flex-col gap-6">
              {debrief && debrief.hindsight.length > 0 && (
                <section className="tile" aria-labelledby="better">
                  <h2 id="better" className="tile-title">
                    What could have been done better
                  </h2>
                  <ul className="brain-hindsight">
                    {debrief.hindsight.map((h) => (
                      <li key={h.text}>
                        {h.text}{" "}
                        <span className="badge" data-tone={h.knowable_before ? "link" : undefined}>
                          {h.knowable_before ? "Knowable before" : "Hindsight only"}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="note">
                    Only what could have been known before the trade can become a lesson.
                  </p>
                </section>
              )}

              {data && <DayLessons record={data} />}
              {note.data && <NoteEditor note={note.data} />}
            </div>

            <aside className="flex flex-col gap-6">
              {note.data && <MiniGraph note={note.data} />}
              {note.data && (
                <section className="tile" aria-labelledby="links">
                  <h2 id="links" className="tile-title">
                    Links
                  </h2>
                  <NoteHeads heads={note.data.links_out} empty="Links to nothing yet." />
                  <h3 className="brain-sheet-h">Linked from</h3>
                  <NoteHeads heads={note.data.backlinks} empty="Nothing links here yet." />
                </section>
              )}
              <section className="tile" aria-labelledby="facts">
                <h2 id="facts" className="tile-title">
                  Facts behind it
                </h2>
                <p className="note">
                  {data?.frozen_at ? (
                    <>
                      {qty(data.fills)} fills, kept in the day's note when the paper account was
                      reset. Numbers here never come from the debrief's text.
                    </>
                  ) : (
                    <>
                      {data ? `${qty(data.fills)} fills` : MISSING} in the{" "}
                      <Link to="/trades" className="wikilink">
                        trade book
                      </Link>
                      . Numbers here are read from the record each time, never from the debrief's
                      text.
                    </>
                  )}
                </p>
              </section>
            </aside>
          </div>
        </div>
      )}
    </Page>
  );
}

/** The lessons checked against the day's runs and orders, then those still owed a check. */
function DayLessons({ record }: { record: DayRecord }) {
  const strategies = useStrategies();
  const names = new Map(
    (strategies.data?.strategies ?? []).map((s) => [s.strategy_id, s.name] as const),
  );
  const total = record.checks.length + record.owed_checks.length;
  if (total === 0) return null;
  return (
    <section className="tile" aria-labelledby="day-lessons">
      <div className="brain-tile-head">
        <h2 id="day-lessons" className="tile-title">
          Lessons
        </h2>
        <span className="count">{total}</span>
      </div>
      <ul className="brain-checks">
        {record.checks.map((c) => (
          <li key={`${c.lesson_id}-${c.run_id ?? c.order_id}`}>
            <span className="badge" data-tone={OUTCOME[c.outcome]?.tone}>
              {OUTCOME[c.outcome]?.label ?? c.outcome}
            </span>
            <div>
              <Link to={`/brain/lessons/${c.lesson_id}`} className="wikilink">
                {c.lesson_title}
              </Link>
              <p className="note">
                {subjectText(c, names)}
                {c.observed && <> · {c.observed}</>} · {c.why}
              </p>
            </div>
          </li>
        ))}
        {record.owed_checks.map((o) => (
          <li key={`${o.lesson_id}-${o.run_id ?? o.order_id}`} data-owed="true">
            <span className="badge" data-tone="warn">
              Owed
            </span>
            <div>
              <Link to={`/brain/lessons/${o.lesson_id}`} className="wikilink">
                {o.lesson_title}
              </Link>
              <p className="note">{subjectText(o, names)} · not checked yet</p>
            </div>
          </li>
        ))}
      </ul>
      {record.owed_checks.length > 0 && (
        <p className="note">
          Owed checks are answered by the debrief: whether each lesson held, with the figure
          observed.
        </p>
      )}
    </section>
  );
}

/** Asks openticker-serve for this day's debrief, again or for the first time. */
function WriteDebrief({ date, written }: { date: string; written: boolean }) {
  const start = useStartDebrief();
  const { notify } = useActions();
  return (
    <button
      type="button"
      className="btn"
      data-size="sm"
      disabled={start.isPending}
      onClick={async () => {
        try {
          const started = await start.mutateAsync(date);
          notify(`${started.job.title} asked for: your coding agent writes it in a few minutes.`);
        } catch (error) {
          notify(error instanceof Error ? error.message : String(error));
        }
      }}
    >
      {written ? "Rewrite debrief" : "Write debrief"}
    </button>
  );
}
