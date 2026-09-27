import type { Schemas } from "../api/client";
import { type Source, sourceLabel } from "./format";

export type Exchange = Schemas["Exchange"];
export type Side = Schemas["Side"];
export type Product = Schemas["Product"];
export type OrderType = Schemas["OrderType"];
export type OrderStatus = Schemas["OrderStatus"];
export type Order = Schemas["OrderbookEntryResult"];

/** What the order dialog opens with. */
export interface OrderDraft {
  symbol: string;
  exchange: Exchange;
  side: Side;
  quantity: number;
  product: Product;
  orderType: OrderType;
  price?: number;
  triggerPrice?: number;
}

/** The contract an order is for, as the instrument master lists it. */
export interface Contract {
  instrument_type: Schemas["InstrumentType"];
  lot_size: number;
  tick_size: number;
}

export const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: "MARKET", label: "Market" },
  { value: "LIMIT", label: "Limit" },
  { value: "SL", label: "SL" },
  { value: "SL-M", label: "SL-M" },
];

export const needsPrice = (type: OrderType) => type === "LIMIT" || type === "SL";
export const needsTrigger = (type: OrderType) => type === "SL" || type === "SL-M";
export const isDerivative = (contract: Contract) =>
  contract.instrument_type === "FUT" ||
  contract.instrument_type === "CE" ||
  contract.instrument_type === "PE";

/** Kite's two products per segment: Intraday MIS, and Longterm CNC or Overnight NRML. */
export function productsFor(contract: Contract): { value: Product; label: string }[] {
  return [
    { value: "MIS", label: "Intraday" },
    isDerivative(contract)
      ? { value: "NRML", label: "Overnight" }
      : { value: "CNC", label: "Longterm" },
  ];
}

const onTick = (value: number, tick: number) => {
  const steps = value / tick;
  return Math.abs(steps - Math.round(steps)) < 1e-6;
};

/** Why the draft can't be placed as it stands, field by field; empty when it can. */
export function problems(
  draft: OrderDraft,
  contract: Contract | undefined,
): Partial<Record<"quantity" | "price" | "triggerPrice", string>> {
  const found: Partial<Record<"quantity" | "price" | "triggerPrice", string>> = {};
  if (!Number.isInteger(draft.quantity) || draft.quantity <= 0) {
    found.quantity = "A whole number above 0";
  } else if (contract && draft.quantity % contract.lot_size !== 0) {
    found.quantity = `A multiple of the lot, ${contract.lot_size}`;
  }
  for (const [field, needed, value] of [
    ["price", needsPrice(draft.orderType), draft.price],
    ["triggerPrice", needsTrigger(draft.orderType), draft.triggerPrice],
  ] as const) {
    if (!needed) continue;
    if (value === undefined || !(value > 0)) found[field] = "Required";
    else if (contract && !onTick(value, contract.tick_size)) {
      found[field] = `In steps of ${contract.tick_size}`;
    }
  }
  return found;
}

/** Kite's status words: Open, Trigger pending, Complete, Rejected, Cancelled. */
export function statusLabel(order: Pick<Order, "status" | "order_type" | "triggered">): string {
  switch (order.status) {
    case "PENDING":
      return needsTrigger(order.order_type) && !order.triggered ? "Trigger pending" : "Open";
    case "FILLED":
      return "Complete";
    case "REJECTED":
      return "Rejected";
    case "FAILED":
      return "Failed";
    case "CANCELLED":
      return "Cancelled";
  }
}

/** Who placed it: the strategy's or script's name when there is one. */
export function placedBy(order: { source: string; placed_by?: string | null }): string {
  return order.placed_by ?? sourceLabel(order.source as Source);
}

export type PlacerFilter = "anyone" | "you" | "agents" | "strategies" | "scripts";

const GROUPS: Record<Exclude<PlacerFilter, "anyone">, Source[]> = {
  you: ["you"],
  agents: ["claude-code", "codex", "agent"],
  strategies: ["strategy", "alert"],
  scripts: ["script"],
};

export function placedByAny(order: Pick<Order, "source">, filter: PlacerFilter): boolean {
  return filter === "anyone" || GROUPS[filter].includes(order.source as Source);
}
