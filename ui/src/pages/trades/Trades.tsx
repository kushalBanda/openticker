import { Download } from "lucide-react";
import { Fragment, useState } from "react";
import { type Period, type Trade, useTrades } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { InfoPopover } from "../../components/InfoPopover";
import { Instrument } from "../../components/Instrument";
import { Page } from "../../components/Page";
import { PlacedBy, SideBadge } from "../../components/PlacedBy";
import { Segmented } from "../../components/Segmented";
import { loaded, StatCard } from "../../components/StatCard";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import {
  direction,
  type InstrumentType,
  istClock,
  MISSING,
  price,
  qty,
  rupees,
  signed,
} from "../../lib/format";
import { chargeLines, summarise, tradesCsv } from "../../lib/trades";
import { useLive } from "../../stream/StreamProvider";

const dayParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  weekday: "short",
  day: "numeric",
  month: "short",
});
/** Tue 22 Sep, exchange date (en-GB writes "Sept"). */
const day = (at: Date) => {
  const parts = dayParts.formatToParts(at);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month").slice(0, 3)}`;
};

const PERIODS: { value: Period; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "This week" },
  { value: "month", label: "This month" },
];

function Charges({ trade }: { trade: Trade }) {
  if (trade.charges === null) return <span className="missing">{MISSING}</span>;
  if (!trade.charges_detail) return <>{rupees(trade.charges)}</>;
  return (
    <InfoPopover
      label={`Charges on this fill: ${rupees(trade.charges)}`}
      title="Charges on this fill"
      content={
        <dl className="kv">
          {chargeLines(trade.charges_detail).map((line) => (
            <Fragment key={line.name}>
              <dt className="muted">{line.name}</dt>
              <dd>{rupees(line.amount)}</dd>
            </Fragment>
          ))}
          <dt className="kv-total">Total</dt>
          <dd className="kv-total">{rupees(trade.charges)}</dd>
        </dl>
      }
    >
      {rupees(trade.charges)}
    </InfoPopover>
  );
}

function Realized({ trade }: { trade: Trade }) {
  if (trade.realized_pnl === null) {
    return (
      <span className="missing" title="Not recorded for fills this old">
        {MISSING}
      </span>
    );
  }
  if (trade.realized_pnl === 0) return <span className="muted">{signed(0)}</span>;
  return <span className={direction(trade.realized_pnl)}>{signed(trade.realized_pnl)}</span>;
}

function download(csv: string, name: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** Every fill of the period: value, charges itemised, and what it realized. */
export function Trades() {
  const { status } = useLive();
  const broker = status?.broker;
  const [period, setPeriod] = useState<Period>("today");
  const trades = useTrades(broker, period);
  const rows = trades.data?.trades ?? [];
  const sum = summarise(rows);
  const loading = broker === undefined || trades.isPending;
  const net = sum.realized - sum.charges;
  const share = sum.turnover > 0 ? (sum.charges / sum.turnover) * 100 : null;

  const columns: Column<Trade>[] = [
    {
      key: "time",
      head: "Time",
      align: "left",
      cell: (t) => <span className="muted">{istClock(new Date(t.filled_at))}</span>,
      sub: period === "today" ? undefined : (t) => day(new Date(t.filled_at)),
    },
    {
      key: "instrument",
      head: "Instrument",
      align: "left",
      cell: (t) => (
        <Instrument
          symbol={t.symbol}
          exchange={t.exchange}
          type={t.instrument_type as InstrumentType}
          expiry={t.expiry}
          strike={t.strike}
        />
      ),
    },
    { key: "side", head: "Side", align: "left", cell: (t) => <SideBadge side={t.side} /> },
    {
      key: "product",
      head: "Product",
      align: "left",
      cell: (t) => <span className="badge">{t.product}</span>,
    },
    { key: "qty", head: "Qty.", cell: (t) => qty(t.quantity) },
    { key: "price", head: "Price", cell: (t) => price(t.price) },
    { key: "value", head: "Value", cell: (t) => price(t.value) },
    { key: "charges", head: "Charges", cell: (t) => <Charges trade={t} /> },
    { key: "realized", head: "Realized", cell: (t) => <Realized trade={t} /> },
    { key: "by", head: "Placed by", align: "left", cell: (t) => <PlacedBy row={t} /> },
  ];

  return (
    <Page
      title="Trades"
      actions={
        <>
          <Segmented<Period>
            label="Period"
            value={period}
            onChange={setPeriod}
            segments={PERIODS}
          />
          <button
            type="button"
            className="btn"
            disabled={rows.length === 0}
            onClick={() =>
              download(tradesCsv(rows), `trades-${trades.data?.since.slice(0, 10) ?? period}.csv`)
            }
          >
            <Download aria-hidden />
            CSV
          </button>
        </>
      }
    >
      <div className="stats">
        <StatCard label="Fills" value={loaded(trades, () => sum.fills)} />
        <StatCard label="Turnover" value={loaded(trades, () => rupees(sum.turnover))} />
        <StatCard
          label="Realized P&L"
          testId="realized"
          value={loaded(trades, () => (
            <span className={direction(net)}>{rupees(net, { sign: true })}</span>
          ))}
          note={
            !trades.data
              ? undefined
              : sum.unrecorded > 0
                ? `after charges; ${sum.unrecorded} older fill${sum.unrecorded === 1 ? "" : "s"} not counted`
                : "after charges"
          }
        />
        <StatCard
          label="Charges"
          value={loaded(trades, () => rupees(sum.charges))}
          note={share === null ? undefined : `${Number(share.toPrecision(2))}% of turnover`}
        />
      </div>

      {trades.isError ? (
        <div className="tile empty" role="alert">
          <h2>Trades didn't load</h2>
          <p className="note">{trades.error.message}</p>
          <button type="button" className="btn" onClick={() => trades.refetch()}>
            Try again
          </button>
        </div>
      ) : (
        <section className="tile" data-flush="true" aria-label="Fills">
          {loading ? (
            <TableSkeleton label="Loading trades" rows={3} />
          ) : rows.length === 0 ? (
            <TableEmpty>
              {period === "today"
                ? "No fills today. An order shows here once it trades; resting ones fill when a live price reaches them."
                : "No fills in this period."}
            </TableEmpty>
          ) : (
            <DataTable
              label="Trades"
              columns={columns}
              rows={rows}
              rowKey={(t) => `${t.order_id}:${t.filled_at}`}
            />
          )}
        </section>
      )}
      <p className="note" style={{ marginTop: 16 }}>
        Paper fills pay the bid or ask and Indian charges. Realized is what a fill closed, before
        charges. Fills from before realized P&amp;L and the charge breakdown were recorded show{" "}
        {MISSING}.
      </p>
    </Page>
  );
}
