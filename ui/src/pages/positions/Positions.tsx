import { useCallback, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { type Position, useCloseAll, useFunds, usePositions } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { HoldButton } from "../../components/HoldButton";
import { Instrument, useOpenSymbol } from "../../components/Instrument";
import { LivePrice } from "../../components/LivePrice";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { StatCard } from "../../components/StatCard";
import { direction, MISSING, price, qty, rupees, signed, sourceLabel } from "../../lib/format";
import type { OrderDraft } from "../../lib/orders";
import { livePrice, markToMarket, total } from "../../lib/pnl";
import { useActions } from "../../shell/actions";
import type { InstrumentKey, Tick } from "../../stream/connection";
import { usePrices } from "../../stream/prices";
import { useLive } from "../../stream/StreamProvider";
import { CloseDialog } from "./CloseDialog";

type View = "open" | "closed";
type Kind = "all" | "EQ" | "FUT" | "OPT";

interface Row {
  position: Position;
  key: InstrumentKey;
  tick: Tick | undefined;
  ltp: number | null;
  pnl: number | null;
}

const rowKey = (row: Row) => `${row.key}:${row.position.product}`;

function kindOf(position: Position): Kind {
  const type = position.instrument_type;
  if (type === "CE" || type === "PE") return "OPT";
  return type === "FUT" ? "FUT" : "EQ";
}

/** P&L: signed and coloured; in rupees on a stat card, bare in the table as Kite has it. */
function Money({ value, currency }: { value: number | null; currency?: boolean }) {
  if (value === null) return <span className="missing">{MISSING}</span>;
  return (
    <span className={direction(value)}>
      {currency ? rupees(value, { sign: true }) : signed(value)}
    </span>
  );
}

/** The last price, flashing on a change (DESIGN.md), with Stale after a quiet minute. */
function Ltp({ row, watching }: { row: Row; watching: boolean }) {
  return <LivePrice value={row.ltp} tick={row.tick} watching={watching} />;
}

/** One more lot the same way, at the last price (Kite's Add). */
function addTo(position: Position): OrderDraft {
  return {
    symbol: position.symbol,
    exchange: position.exchange,
    side: position.quantity > 0 ? "BUY" : "SELL",
    quantity: position.lot_size,
    product: position.product,
    orderType: "LIMIT",
  };
}

function HeldBy({ position }: { position: Position }) {
  if (position.held_by.length === 0) return <span className="missing">{MISSING}</span>;
  const strategies = position.held_by.filter((holder) => holder.strategy_id !== null);
  const rest = position.held_by.find((holder) => holder.strategy_id === null);
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {position.shared && (
        <span className="badge" data-tone="warn" title="The strategies' legs don't fit inside it">
          Shared
        </span>
      )}
      {strategies.map((holder) => (
        <Link
          key={holder.strategy_id}
          to={`/strategies/${holder.strategy_id}`}
          className="badge"
          data-tone="name"
        >
          {holder.name ?? "Deleted strategy"}
        </Link>
      ))}
      {rest &&
        (strategies.length > 0 ? (
          <span className="muted">
            + {sourceLabel(rest.source).toLowerCase()} {qty(Math.abs(rest.quantity))}
          </span>
        ) : (
          <span className="muted">{sourceLabel(rest.source)}</span>
        ))}
    </span>
  );
}

function Skeleton() {
  return (
    <div
      className="tile"
      data-flush="true"
      role="status"
      aria-busy="true"
      aria-label="Loading positions"
    >
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-6 px-6" style={{ height: 44 }}>
          <span className="skeleton" style={{ width: 160 }} />
          <span className="flex-1" />
          <span className="skeleton" style={{ width: 80 }} />
          <span className="skeleton" style={{ width: 80 }} />
        </div>
      ))}
    </div>
  );
}

export function Positions() {
  const { status } = useLive();
  const broker = status?.broker;
  const marketOpen = status?.market_open ?? false;
  const [view, setView] = useState<View>("open");
  const [kind, setKind] = useState<Kind>("all");
  const [closing, setClosing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const open = usePositions(broker, false);
  const withClosed = usePositions(view === "closed" ? broker : undefined, true);
  const funds = useFunds(broker);
  const closeAll = useCloseAll();
  const { order } = useActions();
  const openSymbol = useOpenSymbol();
  const source = view === "open" ? open : withClosed;

  const listed = useMemo(
    () =>
      (source.data?.positions ?? []).filter(
        (p) =>
          (view === "open" ? p.quantity !== 0 : p.quantity === 0) &&
          (kind === "all" || kindOf(p) === kind),
      ),
    [source.data, view, kind],
  );
  const openPositions = open.data?.positions ?? [];
  const keys = useMemo(
    () => openPositions.map((p) => `${p.exchange}:${p.symbol}` as InstrumentKey),
    [openPositions],
  );
  const ticks = usePrices(keys);

  const live = useMemo(() => {
    const byKey = new Map<string, Tick | undefined>(keys.map((key, i) => [key, ticks[i]]));
    return (position: Position): Row => {
      const key = `${position.exchange}:${position.symbol}` as InstrumentKey;
      const tick = byKey.get(key);
      if (position.quantity === 0) {
        return { position, key, tick, ltp: position.last_price, pnl: position.realized_pnl };
      }
      const ltp = livePrice(position, open.dataUpdatedAt, tick);
      return { position, key, tick, ltp, pnl: markToMarket(position, ltp) };
    };
  }, [keys, ticks, open.dataUpdatedAt]);

  const rows = listed.map(live);
  const openRows = openPositions.map(live);
  const openPnl = open.data ? total(openRows.map((row) => row.pnl)) : null;
  const shownTotal = total(rows.map((row) => row.pnl));
  const heldByStrategies = openPositions.filter((p) =>
    p.held_by.some((holder) => holder.strategy_id !== null),
  ).length;
  const closingRow = openPositions.find(
    (p) => `${p.exchange}:${p.symbol}:${p.product}` === closing,
  );
  // Kept after closing, so the dialog can leave the way it came.
  const lastClosing = useRef<Position | undefined>(undefined);
  if (closingRow) lastClosing.current = closingRow;
  const dialogFor = lastClosing.current;

  const onDone = useCallback((message: string) => {
    setClosing(null);
    setNotice(message);
  }, []);

  const columns: Column<Row>[] = [
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
      key: "product",
      head: "Product",
      align: "left",
      cell: ({ position }) => <span className="badge">{position.product}</span>,
    },
    {
      key: "held",
      head: "Held by",
      align: "left",
      wrap: true,
      cell: ({ position }) => <HeldBy position={position} />,
    },
    {
      key: "qty",
      head: "Qty.",
      cell: ({ position }) => (
        <span className={direction(position.quantity)}>{qty(position.quantity)}</span>
      ),
    },
    { key: "avg", head: "Avg.", cell: ({ position }) => price(position.average_price) },
    {
      key: "ltp",
      head: "LTP",
      cell: (row) => <Ltp row={row} watching={marketOpen && row.position.quantity !== 0} />,
    },
    { key: "pnl", head: "P&L", cell: (row) => <Money value={row.pnl} /> },
    {
      key: "chg",
      head: "Chg.",
      cell: (row) => {
        const cost = row.position.average_price * Math.abs(row.position.quantity);
        if (row.pnl === null || cost === 0 || row.position.quantity === 0) {
          return <span className="missing">{MISSING}</span>;
        }
        const pct = (row.pnl / cost) * 100;
        return <span className={direction(pct)}>{signed(pct)}%</span>;
      },
    },
  ];

  const count = view === "open" ? openPositions.length : undefined;
  const loading = broker === undefined || source.isPending;

  return (
    <Page
      title="Positions"
      count={open.data ? openPositions.length : undefined}
      actions={
        view === "open" &&
        openPositions.length > 0 && (
          <HoldButton
            label={marketOpen ? "Hold to close all positions" : "Market closed"}
            disabled={!marketOpen || broker === undefined}
            onConfirm={async () => {
              if (!broker) return;
              try {
                const result = await closeAll.mutateAsync(broker);
                const failed = result.orders.filter((o) => o.status !== "FILLED");
                const closed = result.orders.length - failed.length;
                setNotice(
                  failed.length === 0
                    ? `Closed ${closed} position${closed === 1 ? "" : "s"} at the market.`
                    : `Closed ${closed}. Not closed: ${failed
                        .map((o) => `${o.symbol} (${o.reason ?? o.status})`)
                        .join(", ")}.`,
                );
              } catch (error) {
                setNotice(error instanceof Error ? error.message : String(error));
              }
            }}
          />
        )
      }
    >
      <div className="stats">
        <StatCard
          label="Open P&L"
          testId="open-pnl"
          value={
            open.data ? (
              <Money value={openPnl} currency />
            ) : (
              <span className="skeleton" style={{ width: 120 }} />
            )
          }
          tone={undefined}
          note={marketOpen ? "marked live" : "at the last price"}
        />
        <StatCard
          label="Realized"
          value={
            funds.data ? (
              <Money value={funds.data.realized_pnl - funds.data.charges} currency />
            ) : (
              <span className="skeleton" style={{ width: 120 }} />
            )
          }
          note={funds.data ? `after ${rupees(funds.data.charges)} charges, all time` : undefined}
        />
        <StatCard
          label="Margin used"
          value={
            funds.data ? (
              rupees(funds.data.used_margin)
            ) : (
              <span className="skeleton" style={{ width: 120 }} />
            )
          }
          note={
            funds.data && funds.data.total_capital > 0
              ? `${Math.round((funds.data.used_margin / funds.data.total_capital) * 100)}% of capital`
              : undefined
          }
        />
        <StatCard
          label="Positions"
          value={
            open.data ? openPositions.length : <span className="skeleton" style={{ width: 40 }} />
          }
          note={open.data ? `${heldByStrategies} held by strategies` : undefined}
        />
      </div>

      {status && !status.broker_connected && (
        <div className="notice" role="status">
          <span className="badge" data-tone="warn">
            No broker
          </span>
          <span>
            Connect {status.broker === "zerodha" ? "Zerodha" : status.broker} to get live prices.
          </span>
          <span className="flex-1" />
          <Link to="/settings">Settings ›</Link>
        </div>
      )}
      {notice && (
        <div className="notice" role="status" data-testid="notice">
          <span>{notice}</span>
          <span className="flex-1" />
          <button
            type="button"
            className="btn"
            data-variant="ghost"
            data-size="sm"
            onClick={() => setNotice(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="toolbar">
        <Segmented<View>
          label="Open or closed"
          value={view}
          onChange={setView}
          segments={[
            { value: "open", label: "Open", count },
            { value: "closed", label: "Closed" },
          ]}
        />
        <span className="flex-1" />
        <Segmented<Kind>
          label="Instrument type"
          value={kind}
          onChange={setKind}
          segments={[
            { value: "all", label: "All" },
            { value: "EQ", label: "EQ" },
            { value: "FUT", label: "FUT" },
            { value: "OPT", label: "OPT" },
          ]}
        />
      </div>

      {loading ? (
        <Skeleton />
      ) : source.isError ? (
        <div className="tile empty" role="alert">
          <h2>Positions didn't load</h2>
          <p className="note">{source.error.message}</p>
          <button type="button" className="btn" onClick={() => source.refetch()}>
            Try again
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="tile empty">
          <h2>{view === "open" ? "No open positions" : "No closed positions"}</h2>
          <p className="note">
            {view === "open"
              ? "Place a paper order, or ask your agent to: place_order."
              : "Positions closed in the paper account show here with their realized P&L."}
          </p>
        </div>
      ) : (
        <div className="tile" data-flush="true">
          <DataTable
            label="Positions"
            columns={columns}
            rows={rows}
            rowKey={rowKey}
            selected={closing ?? undefined}
            onSelect={(key) => {
              const [exchange = "", symbol = ""] = key.split(":");
              openSymbol(exchange, symbol);
            }}
            actions={
              view === "open"
                ? (row) => (
                    <>
                      <button
                        type="button"
                        className="btn"
                        data-variant="ghost"
                        data-size="sm"
                        onClick={() => order(addTo(row.position))}
                      >
                        Add
                      </button>
                      <button
                        type="button"
                        className="btn"
                        data-variant="ghost"
                        data-size="sm"
                        onClick={() => setClosing(rowKey(row))}
                      >
                        Close
                      </button>
                    </>
                  )
                : undefined
            }
            total={
              <tr className="total">
                <td colSpan={6} data-align="left">
                  Total
                </td>
                <td>
                  <Money value={shownTotal} />
                </td>
                <td />
              </tr>
            }
          />
        </div>
      )}
      <p className="note" style={{ marginTop: 16 }}>
        MIS positions are squared off at 15:20 IST. P&L moves with every tick; the server's figure
        replaces it after each close and every 30 seconds.
      </p>

      {dialogFor && broker && (
        <CloseDialog
          key={`${dialogFor.exchange}:${dialogFor.symbol}:${dialogFor.product}`}
          open={closingRow !== undefined}
          position={dialogFor}
          broker={broker}
          marketOpen={marketOpen}
          onClose={() => setClosing(null)}
          onDone={onDone}
        />
      )}
    </Page>
  );
}
