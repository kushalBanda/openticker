import { Link } from "react-router";
import type { Schemas } from "../../api/client";
import type { DayPnl } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { Instrument, useOpenSymbol } from "../../components/Instrument";
import { type Failure, TableEmpty, TableFailed } from "../../components/TableStates";
import { byLabel, describe } from "../../lib/events";
import {
  direction,
  istClock,
  MISSING,
  percent,
  price,
  qty,
  rupees,
  signed,
  sourceLabel,
} from "../../lib/format";
import { type Strategy, stateBadge } from "../../lib/strategies";
import { type CalendarDay, dayStats, weeks } from "../../lib/today";
import type { AuditEntry } from "../../stream/connection";

type Position = Schemas["PositionResult"];

export interface LiveRow {
  position: Position;
  ltp: number | null;
  pnl: number | null;
}

function heldBy(position: Position): string {
  const strategies = position.held_by.filter((h) => h.strategy_id !== null);
  const rest = position.held_by.find((h) => h.strategy_id === null);
  if (!strategies.length) return rest ? sourceLabel(rest.source) : MISSING;
  const names = strategies.map((h) => h.name ?? "Deleted strategy").join(", ");
  return rest ? `${names} + ${sourceLabel(rest.source).toLowerCase()}` : names;
}

export function OpenPositionsTile({
  rows,
  loading,
  failed,
}: {
  rows: LiveRow[];
  loading: boolean;
  failed?: Failure;
}) {
  const openSymbol = useOpenSymbol();
  const columns: Column<LiveRow>[] = [
    {
      key: "instrument",
      head: "Instrument",
      align: "left",
      cell: ({ position: p }) => (
        <Instrument
          symbol={p.symbol}
          exchange={p.exchange}
          type={p.instrument_type}
          expiry={p.expiry}
          strike={p.strike}
        />
      ),
    },
    {
      key: "held",
      head: "Held by",
      align: "left",
      cell: ({ position }) => <span className="muted">{heldBy(position)}</span>,
    },
    {
      key: "qty",
      head: "Qty.",
      cell: ({ position }) => (
        <span className={direction(position.quantity)}>{qty(position.quantity)}</span>
      ),
    },
    { key: "ltp", head: "LTP", cell: ({ ltp }) => (ltp === null ? MISSING : price(ltp)) },
    {
      key: "pnl",
      head: "P&L",
      cell: ({ pnl }) =>
        pnl === null ? (
          <span className="missing">{MISSING}</span>
        ) : (
          <span className={direction(pnl)}>{signed(pnl)}</span>
        ),
    },
  ];
  return (
    <section className="tile" data-flush="true" aria-labelledby="open-positions">
      <div className="tile-head">
        <h2 id="open-positions">Open positions</h2>
        <span className="flex-1" />
        <Link to="/positions" className="more-link">
          All positions ›
        </Link>
      </div>
      {failed ? (
        <TableFailed what="Positions" failure={failed} />
      ) : !loading && rows.length === 0 ? (
        <TableEmpty>
          No open positions. Fills from you, your agents and strategies show here.
        </TableEmpty>
      ) : (
        <DataTable
          label="Open positions"
          columns={columns}
          rows={rows.slice(0, 6)}
          rowKey={(r) => `${r.position.exchange}:${r.position.symbol}:${r.position.product}`}
          onSelect={(key) => {
            const [exchange = "", symbol = ""] = key.split(":");
            openSymbol(exchange, symbol);
          }}
        />
      )}
    </section>
  );
}

/** A half ring: how much of the capital is blocked as margin. */
function Gauge({ used }: { used: number }) {
  const share = Math.max(0, Math.min(1, used));
  const arc = Math.PI * 40;
  return (
    <svg
      viewBox="0 0 100 56"
      className="gauge"
      role="img"
      aria-label={`${percent(share)}% of capital used`}
    >
      <path d="M10 50 A40 40 0 0 1 90 50" className="gauge-track" />
      <path
        d="M10 50 A40 40 0 0 1 90 50"
        className="gauge-fill"
        strokeDasharray={`${arc * share} ${arc}`}
      />
      <text x="50" y="47" textAnchor="middle" className="gauge-text">
        {percent(share)}
        <tspan className="gauge-unit">%</tspan>
      </text>
    </svg>
  );
}

export function MarginTile({
  funds,
  failed,
}: {
  funds: Schemas["FundsResult"] | undefined;
  failed?: Failure;
}) {
  const used = funds ? funds.used_margin / funds.total_capital : 0;
  return (
    <section className="tile" aria-labelledby="margin-title">
      <h2 className="tile-title" id="margin-title">
        Margin used
      </h2>
      {failed ? (
        <TableFailed what="Funds" failure={failed} />
      ) : (
        <div className="margin-row">
          <Gauge used={used} />
          <div className="kv grow">
            <span className="muted">Used</span>
            <span className="tabular">{rupees(funds?.used_margin)}</span>
            <span className="muted">Available</span>
            <span className="tabular">{rupees(funds?.available_cash)}</span>
            <span className="muted">Capital</span>
            <span className="tabular">{rupees(funds?.total_capital)}</span>
            <span className="muted">Charges paid</span>
            <span className="tabular">{rupees(funds?.charges)}</span>
          </div>
        </div>
      )}
    </section>
  );
}

const shade = (net: number | null, scale: number) => {
  if (net === null || net === 0 || scale === 0) return undefined;
  return String(Math.min(4, Math.max(1, Math.ceil((Math.abs(net) / scale) * 4))));
};

export function DailyCalendar({
  days,
  from,
  to,
  failed,
}: {
  days: DayPnl[];
  from: string;
  to: string;
  failed?: Failure;
}) {
  const calendar: CalendarDay[] = days.map((d) => ({
    date: d.trading_date,
    net: d.net_pnl ?? null,
    estimated: d.estimated,
  }));
  const grid = weeks(calendar, from, to);
  const stats = dayStats(calendar);
  const scale = Math.max(1, ...calendar.map((d) => Math.abs(d.net ?? 0)));
  const first = days[0]?.trading_date;

  return (
    <section className="tile" aria-labelledby="daily-title">
      <div className="settings-head">
        <h2 className="tile-title" id="daily-title">
          Daily P&L
        </h2>
        <span className="flex-1" />
        <span className="note">
          {first ? `Recorded since ${first} · after charges` : "After charges"}
        </span>
      </div>
      <div
        className="heatmap"
        role="img"
        aria-label={
          stats
            ? `Daily P&L after charges: ${stats.winning} winning days of ${stats.days} recorded`
            : "Daily P&L after charges: no days recorded yet"
        }
      >
        {grid.map((week, w) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: weeks are fixed columns
          <div className="heatmap-week" key={w}>
            {week.map((day, i) =>
              day === null ? (
                // biome-ignore lint/suspicious/noArrayIndexKey: an empty weekday slot
                <span key={i} className="heatmap-day" data-empty="true" />
              ) : (
                <span
                  key={day.date}
                  className="heatmap-day"
                  data-tone={
                    day.net === null
                      ? undefined
                      : day.net > 0
                        ? "up"
                        : day.net < 0
                          ? "down"
                          : undefined
                  }
                  data-level={shade(day.net, scale)}
                  title={`${day.date}: ${day.net === null ? "no record" : rupees(day.net, { sign: true })}${day.estimated ? " (est.)" : ""}`}
                />
              ),
            )}
          </div>
        ))}
      </div>
      {failed ? (
        <TableFailed what="Daily P&L" failure={failed} />
      ) : stats ? (
        <div className="calendar-stats">
          <span className="note">
            Best day <span className="up tabular">{rupees(stats.best, { sign: true })}</span>
          </span>
          <span className="note">
            Worst day <span className="down tabular">{rupees(stats.worst, { sign: true })}</span>
          </span>
          <span className="note">
            Winning days{" "}
            <span className="tabular">
              {stats.winning} of {stats.days}
            </span>
          </span>
        </div>
      ) : (
        <p className="note settings-note">
          A day is recorded after each close while openticker-serve runs.
        </p>
      )}
    </section>
  );
}

const CHARGE_NAMES: Record<string, string> = {
  brokerage: "Brokerage",
  transaction_tax: "STT",
  exchange: "Exchange",
  exchange_txn: "Exchange",
  sebi: "SEBI",
  stamp_duty: "Stamp",
  gst: "GST",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function ChargesTile({
  summary,
  failed,
}: {
  summary: Schemas["ChargesSummaryResult"] | undefined;
  failed?: Failure;
}) {
  const months = summary?.months ?? [];
  const top = Math.max(1, ...months.map((m) => m.total));
  const byType: Record<string, number> = {};
  for (const month of months) {
    for (const [name, amount] of Object.entries(month.by_type)) {
      byType[name] = (byType[name] ?? 0) + amount;
    }
  }
  return (
    <section className="tile" aria-labelledby="charges-month-title">
      <div className="settings-head">
        <h2 className="tile-title" id="charges-month-title">
          Charges by month
        </h2>
        <span className="flex-1" />
        <span className="note tabular">{rupees(summary?.total)}</span>
      </div>
      {failed ? (
        <TableFailed what="Charges" failure={failed} />
      ) : summary === undefined ? null : months.length === 0 ? (
        <p className="note settings-note">No fills yet, so no charges.</p>
      ) : (
        <>
          <ul className="bars" aria-label="Charges by month">
            {months.map((m) => (
              <li className="bar" key={m.month} title={`${m.month}: ${rupees(m.total)}`}>
                <span className="bar-fill" style={{ height: `${(m.total / top) * 100}%` }} />
                <span className="bar-label">{MONTHS[Number(m.month.slice(5)) - 1]}</span>
              </li>
            ))}
          </ul>
          <p className="note settings-note">
            {Object.entries(byType)
              .map(
                ([name, amount]) =>
                  `${CHARGE_NAMES[name] ?? name} ${rupees(amount, { decimals: 0 })}`,
              )
              .join(" · ")}
          </p>
        </>
      )}
    </section>
  );
}

export function StrategiesTile({
  strategies,
  failed,
}: {
  strategies: Strategy[] | undefined;
  failed?: Failure;
}) {
  const order = { killed: 0, running: 1, listening: 2, scheduled: 3, stopped: 4 } as const;
  const shown = [...(strategies ?? [])].sort((a, b) => order[a.state] - order[b.state]).slice(0, 5);
  return (
    <section className="tile" data-flush="true" aria-labelledby="dash-strategies">
      <div className="tile-head">
        <h2 id="dash-strategies">Strategies</h2>
        <span className="flex-1" />
        <Link to="/strategies" className="more-link">
          All strategies ›
        </Link>
      </div>
      {failed ? (
        <TableFailed what="Strategies" failure={failed} />
      ) : strategies && shown.length === 0 ? (
        <TableEmpty>No strategies yet. Ask your agent to create one.</TableEmpty>
      ) : (
        <ul className="dash-list">
          {shown.map((s) => {
            const badge = stateBadge(s.state);
            return (
              <li key={s.strategy_id}>
                <Link to={`/strategies/${s.strategy_id}`} className="row-link">
                  {s.name}
                </Link>
                <span className="note">{s.kind === "options" ? "Options" : "Signal"}</span>
                <span className="flex-1" />
                <span className="badge" data-tone={badge.tone}>
                  {badge.label}
                </span>
                <span className={`tabular dash-amount ${direction(s.today_pnl) ?? ""}`}>
                  {s.today_pnl ? signed(s.today_pnl) : MISSING}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function RecentEventsTile({
  entries,
  names,
  failed,
}: {
  entries: AuditEntry[] | undefined;
  names: ReadonlyMap<string, string>;
  failed?: Failure;
}) {
  return (
    <section className="tile" data-flush="true" aria-labelledby="dash-events">
      <div className="tile-head">
        <h2 id="dash-events">Recent events</h2>
        <span className="flex-1" />
        <Link to="/activity" className="more-link">
          Activity ›
        </Link>
      </div>
      {failed ? (
        <TableFailed what="Recent events" failure={failed} />
      ) : entries && entries.length === 0 ? (
        <TableEmpty>Nothing yet. Orders, fills, strategies and reviews show up here.</TableEmpty>
      ) : (
        <ul className="dash-list">
          {(entries ?? []).map((entry) => {
            const said = describe(entry, names);
            return (
              <li key={entry.id}>
                <span className="tabular muted dash-time">
                  {istClock(new Date(entry.occurred_at))}
                </span>
                <span className="badge" data-tone={said.tone}>
                  {said.kind}
                </span>
                <span className="dash-text">{said.text}</span>
                <span className="note">{byLabel(entry, names)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
