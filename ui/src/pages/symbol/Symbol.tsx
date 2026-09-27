import NumberFlow from "@number-flow/react";
import { Star } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import {
  type Depth,
  type Position,
  useBars,
  useCreateWatchlist,
  useDepth,
  useListings,
  useOrders,
  usePositions,
  useTrades,
  useWatch,
  useWatchlists,
} from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import type { From } from "../../components/Instrument";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { StatCard } from "../../components/StatCard";
import { TableSkeleton } from "../../components/TableStates";
import {
  type Candle,
  CHOICES,
  choiceOf,
  clockSeconds,
  daysBefore,
  toWeeks,
} from "../../lib/candles";
import {
  change,
  direction,
  type InstrumentType,
  instrumentName,
  MISSING,
  price,
  qty,
  rupees,
} from "../../lib/format";
import type { Exchange, OrderDraft, Side } from "../../lib/orders";
import { markToMarket } from "../../lib/pnl";
import { pickList, savedListId } from "../../lib/watchlists";
import { useActions } from "../../shell/actions";
import { useSideKeys } from "../../shell/keys";
import type { InstrumentKey } from "../../stream/connection";
import { usePrice } from "../../stream/prices";
import { useLive, useServerNow } from "../../stream/StreamProvider";
import { OrderBook } from "../orders/OrderBook";

// lightweight-charts loads with the first chart, not with the app.
const CandleChart = lazy(() =>
  import("../../components/CandleChart").then((m) => ({ default: m.CandleChart })),
);

type Tab = "chart" | "orders";
const FIGURE = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;
const INTERVAL_KEY = "symbol.interval";

function savedInterval(): string {
  try {
    const saved = localStorage.getItem(INTERVAL_KEY);
    if (saved && CHOICES.some((c) => c.key === saved)) return saved;
  } catch {
    // storage blocked: the default
  }
  return "5minute";
}

interface Level {
  n: number;
  bid?: Depth["bids"][number];
  ask?: Depth["asks"][number];
}

const cell = (value: number | undefined, show: (v: number) => string, tone?: string) =>
  value === undefined ? (
    <span className="missing">{MISSING}</span>
  ) : (
    <span className={tone}>{show(value)}</span>
  );

const DEPTH_COLUMNS: Column<Level>[] = [
  { key: "bid", head: "Bid", cell: (l) => cell(l.bid?.price, price, "up") },
  {
    key: "bid-orders",
    head: "Orders",
    className: "depth-orders",
    cell: (l) => cell(l.bid?.orders, qty, "muted"),
  },
  { key: "bid-qty", head: "Qty.", cell: (l) => cell(l.bid?.quantity, qty) },
  { key: "ask", head: "Offer", cell: (l) => cell(l.ask?.price, price, "down") },
  {
    key: "ask-orders",
    head: "Orders",
    className: "depth-orders",
    cell: (l) => cell(l.ask?.orders, qty, "muted"),
  },
  { key: "ask-qty", head: "Qty.", cell: (l) => cell(l.ask?.quantity, qty) },
];

function DepthTile({ depth, loading }: { depth: Depth | undefined; loading: boolean }) {
  const levels: Level[] = [0, 1, 2, 3, 4].map((n) => ({
    n,
    bid: depth?.bids[n],
    ask: depth?.asks[n],
  }));
  return (
    <section className="tile depth-tile" data-flush="true" aria-labelledby="depth-title">
      <div className="tile-head">
        <h2 id="depth-title">Market depth</h2>
      </div>
      {loading ? (
        <TableSkeleton label="Loading market depth" />
      ) : (
        <>
          <DataTable
            label="Market depth"
            dense
            columns={DEPTH_COLUMNS}
            rows={levels}
            rowKey={(l) => String(l.n)}
          />
          <div className="depth-total">
            <span className="note">Total</span>
            <span className="flex-1" />
            <span className="up tabular">{qty(depth?.total_buy_quantity)}</span>
            <span className="muted">/</span>
            <span className="down tabular">{qty(depth?.total_sell_quantity)}</span>
          </div>
        </>
      )}
    </section>
  );
}

function PositionCard({ position, ltp }: { position: Position | undefined; ltp: number | null }) {
  if (!position) {
    return (
      <StatCard
        label="Your position"
        value={<span className="missing">None</span>}
        note="Nothing open"
        testId="your-position"
      />
    );
  }
  const pnl = markToMarket(position, ltp ?? position.last_price);
  return (
    <StatCard
      label="Your position"
      value={`${qty(position.quantity)} · ${position.product}`}
      note={
        <span className={direction(pnl) ?? ""}>
          {pnl === null ? MISSING : rupees(pnl, { sign: true })} · avg.{" "}
          {price(position.average_price)}
        </span>
      }
      testId="your-position"
    />
  );
}

/**
 * On the list the Watchlist page showed last (ADR 36), or off it. With no
 * list yet, the first click makes one called Watchlist.
 */
function WatchButton({
  symbol,
  exchange,
  disabled,
}: {
  symbol: string;
  exchange: Exchange;
  disabled: boolean;
}) {
  const lists = useWatchlists();
  const create = useCreateWatchlist();
  const watch = useWatch();
  const { notify } = useActions();
  const list = pickList(lists.data?.watchlists ?? [], savedListId());
  const on = list?.items.some((i) => i.symbol === symbol && i.exchange === exchange) ?? false;
  const busy = lists.isPending || create.isPending || watch.isPending;

  const toggle = async () => {
    try {
      const target = list ?? (await create.mutateAsync("Watchlist"));
      await watch.mutateAsync({
        id: target.watchlist_id,
        instruments: [{ symbol, exchange }],
        add: !on,
      });
      notify(on ? `Removed from ${target.name}` : `Added to ${target.name}`);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <button
      type="button"
      className="btn"
      data-variant="ghost"
      aria-pressed={on}
      disabled={disabled || busy}
      onClick={toggle}
      title={on ? `Remove from ${list?.name}` : `Add to ${list?.name ?? "a watchlist"}`}
    >
      <Star size={16} aria-hidden className="watch-star" />
      {on ? `On ${list?.name}` : "Watch"}
    </button>
  );
}

/**
 * One instrument (DESIGN.md Symbol): its quote as stat cards, candles with
 * your paper fills, market depth, today's orders for it, and the order
 * window from "Place paper order" or B / S.
 */
export function SymbolPage() {
  const params = useParams();
  // The way out: back to the page it was opened from; opened directly, the Watchlist.
  const came = (useLocation().state as { from?: From } | null)?.from;
  const back = came ?? { to: "/watchlist", label: "Watchlist" };
  const exchange = (params.exchange ?? "NSE").toUpperCase() as Exchange;
  const symbol = params.symbol ?? "";
  const { status } = useLive();
  const broker = status?.broker;
  const now = useServerNow();
  const { order } = useActions();
  const [tab, setTab] = useState<Tab>("chart");
  const [interval, setIntervalChoice] = useState<string>(savedInterval);
  const choice = choiceOf(interval);

  const listings = useListings(symbol);
  const contract = listings.data?.find((i) => i.exchange === exchange);
  const depth = useDepth(contract ? broker : undefined, exchange, symbol);
  const tick = usePrice(`${exchange}:${symbol}` as InstrumentKey);
  const today = new Date(now().getTime() + 330 * 60_000).toISOString().slice(0, 10);
  const bars = useBars(
    contract ? broker : undefined,
    exchange,
    symbol,
    choice.interval,
    daysBefore(today, choice.days),
    today,
  );
  const positions = usePositions(broker, false);
  const orders = useOrders(broker);
  const trades = useTrades(broker, "month");

  const { name, tag } = instrumentName(
    symbol,
    exchange,
    contract?.instrument_type as InstrumentType | undefined,
    contract?.expiry,
    contract?.strike,
  );
  const ltp = tick?.last_price ?? depth.data?.last_price ?? null;
  const prevClose = depth.data?.prev_close ?? null;
  const moved = ltp !== null && prevClose ? ltp - prevClose : null;
  const movedPct = moved !== null && prevClose ? (moved / prevClose) * 100 : null;
  const bid = depth.data?.bids[0]?.price;
  const ask = depth.data?.asks[0]?.price;
  const position = positions.data?.positions.find(
    (p) => p.symbol === symbol && p.exchange === exchange && p.quantity !== 0,
  );
  const mine = (orders.data?.orders ?? []).filter(
    (o) => o.symbol === symbol && o.exchange === exchange,
  );
  const fills = useMemo(
    () => (trades.data?.trades ?? []).filter((t) => t.symbol === symbol && t.exchange === exchange),
    [trades.data, symbol, exchange],
  );
  const candles: Candle[] = useMemo(() => {
    const shown = (bars.data?.bars ?? []).map((b) => ({
      time: clockSeconds(b.timestamp),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    return choice.weekly ? toWeeks(shown) : shown;
  }, [bars.data, choice.weekly]);
  const live = useMemo(
    () => (tick ? { price: tick.last_price, at: tick.as_of } : undefined),
    [tick],
  );

  const open = useMemo(
    () => (side: Side) => {
      if (!contract) return;
      const draft: OrderDraft = {
        symbol,
        exchange,
        side,
        quantity: contract.lot_size,
        product: "MIS",
        orderType: "LIMIT",
      };
      order(draft);
    },
    [contract, symbol, exchange, order],
  );
  useSideKeys(open);

  const pick = (value: string) => {
    setIntervalChoice(value);
    try {
      localStorage.setItem(INTERVAL_KEY, value);
    } catch {
      // storage blocked: this visit only
    }
  };

  if (listings.isSuccess && !contract) {
    return (
      <Page title={symbol || "Symbol"} back={back}>
        <div className="tile empty">
          <h2>
            No {symbol} on {exchange}
          </h2>
          <p className="note">
            It isn't in the instrument list. If it's new or a fresh expiry, sync instruments in{" "}
            <Link to="/settings#instruments">Settings</Link>, or press ⌘K to search.
          </p>
        </div>
      </Page>
    );
  }

  const meta = contract
    ? [
        exchange,
        `Lot ${qty(contract.lot_size)}`,
        `Tick ${contract.tick_size}`,
        contract.expiry ? `Expires ${contract.expiry}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;
  const currency = contract?.instrument_type !== "INDEX";

  return (
    <Page
      title={name}
      back={back}
      badges={
        <>
          {tag && <span className="ex-tag">{tag}</span>}
          {meta && <span className="muted symbol-meta">{meta}</span>}
        </>
      }
      actions={
        <>
          <WatchButton symbol={symbol} exchange={exchange} disabled={!contract} />
          {contract?.instrument_type !== "INDEX" && (
            <>
              <button
                type="button"
                className="btn"
                data-variant="outline"
                disabled={!contract}
                onClick={() => open("SELL")}
                title="Sell (S)"
              >
                Sell
              </button>
              <button
                type="button"
                className="btn"
                data-variant="primary"
                disabled={!contract}
                onClick={() => open("BUY")}
                title="Buy (B)"
              >
                Place paper order
              </button>
            </>
          )}
        </>
      }
    >
      <div className="stats symbol-stats">
        <StatCard
          label="LTP"
          testId="ltp"
          value={
            ltp === null ? (
              <span className="missing">{MISSING}</span>
            ) : (
              <span className="tabular" data-testid="ltp-value" data-value={ltp}>
                {currency && "₹"}
                <NumberFlow value={ltp} locales="en-IN" format={FIGURE} />
              </span>
            )
          }
          note={
            <span className={direction(moved) ?? ""}>
              {moved === null ? "No previous close" : change(moved, movedPct)}
            </span>
          }
        />
        <StatCard
          label="Bid / Offer"
          value={`${price(bid)} / ${price(ask)}`}
          note={bid !== undefined && ask !== undefined ? `Spread ${price(ask - bid)}` : "No book"}
        />
        <StatCard
          label="Day's range"
          value={`${price(depth.data?.low)} – ${price(depth.data?.high)}`}
          note={`Open ${price(depth.data?.open)} · Prev. close ${price(prevClose)}`}
        />
        <StatCard
          label="Volume"
          value={qty(depth.data?.volume)}
          note={
            // Kite sends OI 0 for a stock: only futures and options have any.
            depth.data?.open_interest != null && contract?.expiry
              ? `OI ${qty(depth.data.open_interest)}`
              : `Last qty. ${qty(depth.data?.last_quantity)}`
          }
        />
        <PositionCard position={position} ltp={ltp} />
      </div>

      <div className="toolbar">
        <Segmented<Tab>
          label="Sections"
          value={tab}
          onChange={setTab}
          segments={[
            { value: "chart", label: "Chart" },
            { value: "orders", label: "Orders", count: orders.isPending ? undefined : mine.length },
          ]}
        />
      </div>

      {tab === "chart" ? (
        <div className="symbol-grid">
          <section className="tile chart-tile" aria-labelledby="chart-title">
            <div className="chart-head">
              <h2 id="chart-title">{name}</h2>
              <span className="muted">
                {exchange} · {choice.label} · IST
              </span>
              <span className="flex-1" />
              <Segmented<string>
                label="Interval"
                value={interval}
                onChange={pick}
                segments={CHOICES.map((c) => ({ value: c.key, label: c.label }))}
              />
            </div>
            {bars.isError ? (
              <div className="chart-note" role="alert">
                Candles didn't load: {bars.error.message}
              </div>
            ) : bars.data && candles.length === 0 ? (
              <div className="chart-note">No candles for this range.</div>
            ) : (
              <Suspense
                fallback={<div className="skeleton" style={{ width: "100%", height: 440 }} />}
              >
                {bars.data ? (
                  <CandleChart
                    key={interval}
                    candles={candles}
                    choice={choice}
                    live={live}
                    fills={fills}
                    dayUp={(moved ?? 0) >= 0}
                  />
                ) : (
                  <div className="skeleton" style={{ width: "100%", height: 440 }} />
                )}
              </Suspense>
            )}
            <p className="note chart-foot">
              <span className="up">▲</span> <span className="down">▼</span> your paper fills this
              month. Wheel to zoom, drag to pan.
            </p>
          </section>
          <DepthTile depth={depth.data} loading={depth.isPending} />
        </div>
      ) : (
        <OrderBook
          broker={broker}
          orders={mine}
          all={mine}
          loading={orders.isPending}
          cancelAllShown={false}
          noneYet={`No orders for ${name} today. Press B or S to place one.`}
        />
      )}
    </Page>
  );
}
