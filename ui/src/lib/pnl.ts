// Live P&L over the server's figures (ADR 32): the server gives each
// position's quantity, average and a price; the browser marks it to market
// with every newer tick. A refetch brings the server's price back, and the
// newer of the two wins. No price is null, never 0.

export interface Priced {
  quantity: number;
  average_price: number;
  last_price: number | null;
}

export interface Mark {
  last_price: number;
  received?: number; // browser time it arrived (ms)
}

/** (ltp - avg) x qty, signed by the quantity: a short gains as the price falls. */
export function markToMarket(position: Priced, ltp: number | null | undefined): number | null {
  if (ltp == null || !Number.isFinite(ltp)) return null;
  return (ltp - position.average_price) * position.quantity;
}

/** The newer of the server's price (as of its fetch, browser time) and the latest tick. */
export function livePrice(
  position: Priced,
  fetchedAt: number,
  tick: Mark | undefined,
): number | null {
  if (tick === undefined) return position.last_price;
  if (position.last_price === null) return tick.last_price;
  return (tick.received ?? 0) >= fetchedAt ? tick.last_price : position.last_price;
}

/** Sum of P&L, or null when any open position has no price. */
export function total(values: (number | null)[]): number | null {
  let sum = 0;
  for (const value of values) {
    if (value === null) return null;
    sum += value;
  }
  return sum;
}
