import { useState } from "react";
import { useOrders } from "../../api/queries";
import { Page } from "../../components/Page";
import { PortfolioTabs } from "../../components/PortfolioTabs";
import { Segmented } from "../../components/Segmented";
import { type PlacerFilter, placedByAny } from "../../lib/orders";
import { useLive } from "../../stream/StreamProvider";
import { OrderBook } from "./OrderBook";

/** Today's orders, Kite's way: open ones above (modify, cancel), executed below. */
export function Orders() {
  const { status } = useLive();
  const broker = status?.broker;
  const orders = useOrders(broker);
  const [placer, setPlacer] = useState<PlacerFilter>("anyone");
  const all = orders.data?.orders ?? [];
  const loading = broker === undefined || orders.isPending;

  return (
    <Page
      title="Orders"
      tabs={<PortfolioTabs />}
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
          <OrderBook
            broker={broker}
            orders={all.filter((order) => placedByAny(order, placer))}
            all={all}
            loading={loading}
            noneYet={
              all.length === 0
                ? "No orders today. Press ⌘K to find an instrument and place a paper order, or ask your agent to."
                : "No orders from them today."
            }
          />
          <p className="note" style={{ marginTop: 16 }}>
            Today's paper orders. Open orders fill when a live price reaches them; unfilled ones are
            cancelled at the session's end.
          </p>
        </>
      )}
    </Page>
  );
}
