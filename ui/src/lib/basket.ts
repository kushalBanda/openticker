import { dayMonth } from "./format";
import type { Exchange, Side } from "./orders";

/** One leg of the basket on the Option chain page: lots of one contract, one way. */
export interface Leg {
  symbol: string;
  exchange: Exchange;
  side: Side;
  lots: number;
  lotSize: number;
  /** The limit price, picked from the bid or ask and then the user's to change. */
  price: number;
  kind: "CE" | "PE" | "FUT";
  strike: number | null;
  expiry: string;
}

export type Pick = Omit<Leg, "lots">;

export const MAX_LEGS = 20; // what a payoff previews at once (ADR 38)

/**
 * A bid or ask picked from the chain. One more lot of a leg already there the
 * same way, one less the other way (gone at none), else a new leg; the price
 * is the latest pick's.
 */
export function addPick(legs: Leg[], pick: Pick): Leg[] {
  const at = legs.findIndex((l) => l.symbol === pick.symbol && l.exchange === pick.exchange);
  if (at === -1) return legs.length >= MAX_LEGS ? legs : [...legs, { ...pick, lots: 1 }];
  const leg = legs[at] as Leg;
  const lots = leg.side === pick.side ? leg.lots + 1 : leg.lots - 1;
  if (lots === 0) return legs.filter((_, n) => n !== at);
  return legs.map((l, n) =>
    n === at ? { ...l, lots, price: leg.side === pick.side ? pick.price : l.price } : l,
  );
}

export const units = (leg: Leg) => leg.lots * leg.lotSize;

/** Premium in rupees, positive when the basket takes in more than it pays. */
export function netPremium(legs: Leg[]): number {
  return legs
    .filter((l) => l.kind !== "FUT")
    .reduce((sum, l) => sum + (l.side === "SELL" ? 1 : -1) * l.price * units(l), 0);
}

/** "NIFTY 29 Sep", "NIFTY 29 Sep + 6 Oct": the underlying and its expiries. */
export function basketTitle(name: string, legs: Leg[]): string {
  const expiries = [...new Set(legs.filter((l) => l.kind !== "FUT").map((l) => l.expiry))].sort();
  return [name, expiries.map(dayMonth).join(" + ")].filter(Boolean).join(" ");
}

/** Put OI over call OI across the shown strikes; null without calls. */
export function putCallRatio(
  rows: {
    call?: { open_interest: number | null } | null;
    put?: { open_interest: number | null } | null;
  }[],
): number | null {
  let calls = 0;
  let puts = 0;
  for (const row of rows) {
    calls += row.call?.open_interest ?? 0;
    puts += row.put?.open_interest ?? 0;
  }
  return calls > 0 ? puts / calls : null;
}

/** In the money against the underlying: a call below it, a put above it. */
export function inTheMoney(kind: "CE" | "PE", strike: number, underlying: number): boolean {
  return kind === "CE" ? strike < underlying : strike > underlying;
}

const KEY = "options.basket";

/**
 * Each underlying keeps its own basket, which survives a reload and a visit
 * elsewhere, in this browser only.
 */
export function savedBasket(underlying: string): Leg[] {
  try {
    const raw = localStorage.getItem(`${KEY}.${underlying}`);
    const legs = raw ? (JSON.parse(raw) as Leg[]) : [];
    return Array.isArray(legs) ? legs.filter((l) => l && typeof l.symbol === "string") : [];
  } catch {
    return [];
  }
}

export function saveBasket(underlying: string, legs: Leg[]): void {
  try {
    if (legs.length) localStorage.setItem(`${KEY}.${underlying}`, JSON.stringify(legs));
    else localStorage.removeItem(`${KEY}.${underlying}`);
  } catch {
    // storage blocked: this visit only
  }
}
