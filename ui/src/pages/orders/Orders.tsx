import { useMemo, useState } from "react";
import { useCancelAll, useCancelOrder, useOrders } from "../../api/queries";
import { type Column, DataTable } from "../../components/DataTable";
import { HoldButton } from "../../components/HoldButton";
import { Instrument } from "../../components/Instrument";
import { Page } from "../../components/Page";
import { PlacedBy, SideBadge } from "../../components/PlacedBy";
import { Segmented } from "../../components/Segmented";
import { TableEmpty, TableSkeleton } from "../../components/TableStates";
import { istClock, MISSING, price, qty } from "../../lib/format";
import { type Order, type PlacerFilter, placedByAny, statusLabel } from "../../lib/orders";
import { useActions } from "../../shell/actions";
import type { InstrumentKey } from "../../stream/connection";
import { usePrices } from "../../stream/prices";
import { useLive } from "../../stream/StreamProvider";

type Executed = "all" | "FILLED" | "REJECTED" | "CANCELLED";

const time = (order: Order) => istClock(new Date(order.placed_at));
const filled = (order: Order) => (order.status === "FILLED" ? order.quantity : 0);

function Status({ order }: { order: Order }) {
  const tone =
    order.status === "PENDING"
      ? "accent"
      : order.status === "REJECTED" || order.status === "FAILED"
        ? "down"
        : undefined;
  return (
    <span className="badge" data-tone={tone}>
      {statusLabel(order)}
    </span>
  );
}

const instrument: Column<Order> = {
  key: "instrument",
  head: "Instrument",
  align: "left",
  cell: (o) => (
    <Instrument
      symbol={o.symbol}
      exchange={o.exchange}
      type={o.instrument_type}
      expiry={o.expiry}
      strike={o.strike}
    />
  ),
};
const lead: Column<Order>[] = [
  {
    key: "time",
    head: "Time",
    align: "left",
    cell: (o) => <span className="muted">{time(o)}</span>,
  },
  { key: "type", head: "Type", align: "left", cell: (o) => <SideBadge side={o.side} /> },
  instrument,
  {
    key: "product",
    head: "Product",
    align: "left",
    cell: (o) => <span className="badge">{o.product}</span>,
  },
  { key: "qty", head: "Qty.", cell: (o) => `${qty(filled(o))} / ${qty(o.quantity)}` },
];
const tail: Column<Order>[] = [
  { key: "status", head: "Status", align: "left", cell: (o) => <Status order={o} /> },
  { key: "by", head: "Placed by", align: "left", cell: (o) => <PlacedBy row={o} /> },
];

/** Today's orders, Kite's way: open ones above (modify, cancel), executed below. */
export function Orders() {
  const { status } = useLive();
  const broker = status?.broker;
  const { modify, notify } = useActions();
  const orders = useOrders(broker);
  const cancel = useCancelOrder();
  const cancelAll = useCancelAll();
  const [placer, setPlacer] = useState<PlacerFilter>("anyone");
  const [executed, setExecuted] = useState<Executed>("all");

  const all = orders.data?.orders ?? [];
  const mine = all.filter((order) => placedByAny(order, placer));
  const open = mine.filter((order) => order.status === "PENDING");
  const done = mine.filter(
    (order) =>
      order.status !== "PENDING" &&
      (executed === "all" ||
        order.status === executed ||
        (executed === "REJECTED" && order.status === "FAILED")),
  );
  const openAll = all.filter((order) => order.status === "PENDING");

  const keys = useMemo(
    () => [...new Set(open.map((o) => `${o.exchange}:${o.symbol}` as InstrumentKey))],
    [open],
  );
  const ticks = usePrices(keys);
  const ltpOf = (order: Order) => ticks[keys.indexOf(`${order.exchange}:${order.symbol}`)];

  const openColumns: Column<Order>[] = [
    ...lead,
    {
      key: "ltp",
      head: "LTP",
      cell: (o) => {
        const tick = ltpOf(o);
        return tick ? price(tick.last_price) : <span className="missing">{MISSING}</span>;
      },
    },
    {
      key: "price",
      head: "Price",
      cell: (o) => (
        <>
          {o.price !== null ? price(o.price) : null}
          {o.price !== null && o.trigger_price !== null && " / "}
          {o.trigger_price !== null && (
            <>
              {price(o.trigger_price)} <span className="muted">trg.</span>
            </>
          )}
          {o.price === null && o.trigger_price === null && (
            <span className="missing">{MISSING}</span>
          )}
        </>
      ),
    },
    ...tail,
  ];
  const doneColumns: Column<Order>[] = [
    ...lead,
    {
      key: "avg",
      head: "Avg. price",
      cell: (o) =>
        o.fill_price !== null ? price(o.fill_price) : <span className="missing">{MISSING}</span>,
    },
    ...tail,
  ];

  const onCancel = async (order: Order) => {
    if (!broker) return;
    try {
      const result = await cancel.mutateAsync({ orderId: order.order_id, broker });
      notify(
        result.status === "CANCELLED"
          ? `Cancelled ${order.side === "BUY" ? "buy" : "sell"} ${qty(order.quantity)} ${order.symbol}.`
          : `Not cancelled: ${result.reason ?? result.status.toLowerCase()}.`,
      );
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  const loading = broker === undefined || orders.isPending;

  return (
    <Page
      title="Orders"
      actions={
        <Segmented<PlacerFilter>
          label="Placed by"
          value={placer}
          onChange={setPlacer}
          segments={[
            { value: "anyone", label: "Anyone" },
            { value: "you", label: "You" },
            { value: "agents", label: "Agents" },
            { value: "strategies", label: "Strategies" },
            { value: "scripts", label: "Scripts" },
          ]}
        />
      }
    >
      {orders.isError ? (
        <div className="tile empty" role="alert">
          <h2>Orders didn't load</h2>
          <p className="note">{orders.error.message}</p>
          <button type="button" className="btn" onClick={() => orders.refetch()}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <section className="tile" data-flush="true" aria-labelledby="open-orders">
            <div className="tile-head">
              <h2 id="open-orders">
                Open orders{!loading && <span className="count"> ({open.length})</span>}
              </h2>
              <span className="flex-1" />
              {openAll.length > 0 && (
                <HoldButton
                  label="Hold to cancel all"
                  size="sm"
                  disabled={broker === undefined}
                  onConfirm={async () => {
                    if (!broker) return;
                    try {
                      const result = await cancelAll.mutateAsync(broker);
                      const n = result.cancelled.length;
                      notify(
                        result.failed.length === 0
                          ? `Cancelled ${n} open order${n === 1 ? "" : "s"}.`
                          : `Cancelled ${n}. Not cancelled: ${result.failed
                              .map((f) => `${f.order_id} (${f.reason ?? f.status})`)
                              .join(", ")}.`,
                      );
                    } catch (error) {
                      notify(error instanceof Error ? error.message : String(error));
                    }
                  }}
                />
              )}
            </div>
            {loading ? (
              <TableSkeleton label="Loading open orders" />
            ) : open.length === 0 ? (
              <TableEmpty>
                {placer === "anyone"
                  ? "No open orders. A limit or stop order waits here until the price reaches it."
                  : "No open orders from them."}
              </TableEmpty>
            ) : (
              <DataTable
                label="Open orders"
                columns={openColumns}
                rows={open}
                rowKey={(o) => o.order_id}
                actionsAt="instrument"
                actions={(o) => (
                  <>
                    <button
                      type="button"
                      className="btn"
                      data-variant="ghost"
                      data-size="sm"
                      onClick={() => modify(o)}
                    >
                      Modify
                    </button>
                    <button
                      type="button"
                      className="btn"
                      data-variant="ghost"
                      data-size="sm"
                      onClick={() => onCancel(o)}
                    >
                      Cancel
                    </button>
                  </>
                )}
              />
            )}
          </section>

          <section className="tile" data-flush="true" aria-labelledby="executed-orders">
            <div className="tile-head">
              <h2 id="executed-orders">
                Executed orders{!loading && <span className="count"> ({done.length})</span>}
              </h2>
              <span className="flex-1" />
              <Segmented<Executed>
                label="Status"
                value={executed}
                onChange={setExecuted}
                segments={[
                  { value: "all", label: "All" },
                  { value: "FILLED", label: "Complete" },
                  { value: "REJECTED", label: "Rejected" },
                  { value: "CANCELLED", label: "Cancelled" },
                ]}
              />
            </div>
            {loading ? (
              <TableSkeleton label="Loading executed orders" />
            ) : done.length === 0 ? (
              <TableEmpty>
                {all.length === 0
                  ? "No orders today. Press ⌘K to find an instrument and place a paper order, or ask your agent to."
                  : "None with this status."}
              </TableEmpty>
            ) : (
              <DataTable
                label="Executed orders"
                columns={doneColumns}
                rows={done}
                rowKey={(o) => o.order_id}
                detail={(o) =>
                  (o.status === "REJECTED" || o.status === "FAILED") && o.reason ? (
                    <span>{sentence(o.reason)}</span>
                  ) : null
                }
              />
            )}
          </section>
          <p className="note" style={{ marginTop: 16 }}>
            Today's paper orders. Open orders fill when a live price reaches them; unfilled ones are
            cancelled at the session's end.
          </p>
        </>
      )}
    </Page>
  );
}

/** A server reason as a sentence: capitalised, with a full stop. */
function sentence(reason: string): string {
  const trimmed = reason.trim();
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}
