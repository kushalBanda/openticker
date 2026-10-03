import { Link } from "react-router";
import { placedBy } from "../lib/orders";

interface Placed {
  source: string;
  placed_by?: string | null;
  strategy_id: string | null;
}

/** Who placed an order or fill: the strategy (a link to it) or script by name, else who. */
export function PlacedBy({ row }: { row: Placed }) {
  if (row.source === "strategy" && row.strategy_id && row.placed_by) {
    return (
      <Link to={`/strategies/${row.strategy_id}`} className="badge" data-tone="name">
        {row.placed_by}
      </Link>
    );
  }
  if (row.placed_by) {
    return (
      <span className="badge" data-tone="name">
        {row.placed_by}
      </span>
    );
  }
  return <span>{placedBy(row)}</span>;
}

/** Buy in green, Sell in red, as Kite tags them. */
export function SideBadge({ side }: { side: "BUY" | "SELL" }) {
  return (
    <span className="badge" data-tone={side === "BUY" ? "up" : "down"}>
      {side === "BUY" ? "Buy" : "Sell"}
    </span>
  );
}
