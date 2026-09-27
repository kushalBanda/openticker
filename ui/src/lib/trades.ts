import type { Trade } from "../api/queries";
import { type InstrumentType, instrumentName } from "./format";
import { placedBy } from "./orders";

export interface TradeSummary {
  fills: number;
  turnover: number;
  charges: number;
  /** Before charges, over the fills that recorded it. */
  realized: number;
  /** Fills from before realized P&L was recorded. */
  unrecorded: number;
}

export function summarise(trades: Trade[]): TradeSummary {
  let turnover = 0;
  let charges = 0;
  let realized = 0;
  let unrecorded = 0;
  for (const trade of trades) {
    turnover += trade.value;
    charges += trade.charges ?? 0;
    if (trade.realized_pnl === null) unrecorded += 1;
    else realized += trade.realized_pnl;
  }
  return { fills: trades.length, turnover, charges, realized, unrecorded };
}

// data/charges.json's keys, as a contract note names them.
const CHARGE_NAMES: Record<string, string> = {
  brokerage: "Brokerage",
  transaction_tax: "STT",
  exchange_txn: "Exchange",
  sebi: "SEBI",
  stamp_duty: "Stamp duty",
  gst: "GST",
};

/** A fill's charges in contract-note order, GST last; unknown keys keep their place before it. */
export function chargeLines(detail: Record<string, number>): { name: string; amount: number }[] {
  const known = Object.keys(CHARGE_NAMES);
  const rank = (key: string) =>
    key === "gst" ? 99 : known.includes(key) ? known.indexOf(key) : 50;
  return Object.entries(detail)
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([key, amount]) => ({ name: CHARGE_NAMES[key] ?? sentenceCase(key), amount }));
}

const sentenceCase = (key: string) => {
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

const cell = (value: string | number | null) => {
  if (value === null) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

/** The fills as CSV, one row each, exchange-local times, empty where not recorded. */
export function tradesCsv(trades: Trade[]): string {
  const head = [
    "filled_at",
    "instrument",
    "symbol",
    "exchange",
    "side",
    "quantity",
    "price",
    "value",
    "charges",
    "realized_pnl",
    "product",
    "placed_by",
    "order_id",
  ];
  const rows = trades.map((t) => [
    t.filled_at,
    instrumentName(t.symbol, t.exchange, t.instrument_type as InstrumentType, t.expiry, t.strike)
      .name,
    t.symbol,
    t.exchange,
    t.side,
    t.quantity,
    t.price,
    t.value,
    t.charges,
    t.realized_pnl,
    t.product,
    placedBy(t),
    t.order_id,
  ]);
  return `${[head, ...rows].map((row) => row.map(cell).join(",")).join("\n")}\n`;
}
