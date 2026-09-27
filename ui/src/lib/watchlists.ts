// The Watchlist page's arithmetic and the list this browser last showed
// (ADR 36). Plain functions, so they're tested without a page.

import type { Tick } from "../stream/connection";

const LIST_KEY = "watchlist.list";

/** The list this browser showed last, if storage allows. */
export function savedListId(): string | null {
  try {
    return localStorage.getItem(LIST_KEY);
  } catch {
    return null;
  }
}

export function saveListId(id: string) {
  try {
    localStorage.setItem(LIST_KEY, id);
  } catch {
    // storage blocked: this visit only
  }
}

/** The list to show: the one asked for if it still exists, else the first. */
export function pickList<L extends { watchlist_id: string }>(
  lists: L[],
  wanted: string | null,
): L | undefined {
  return lists.find((list) => list.watchlist_id === wanted) ?? lists[0];
}

export interface Moved {
  last: number | null;
  change: number | null;
  pct: number | null;
}

/**
 * The last price and its change from the previous close: the stream's tick
 * when there is one (it carries the change), else the quote's.
 */
export function moved(
  tick: Tick | undefined,
  quote: { last_price: number; prev_close: number | null } | undefined,
): Moved {
  const last = tick?.last_price ?? quote?.last_price ?? null;
  if (tick && tick.change !== null) {
    return { last, change: tick.change, pct: tick.change_pct };
  }
  const close = quote?.prev_close ?? null;
  if (last === null || !close) return { last, change: null, pct: null };
  const change = last - close;
  return { last, change, pct: (change / close) * 100 };
}

/** The row after `current` moving `by` (±1), kept in range; the first when none. */
export function step(keys: string[], current: string | null, by: 1 | -1): string | null {
  if (keys.length === 0) return null;
  const at = current === null ? -1 : keys.indexOf(current);
  if (at === -1) return keys[by === 1 ? 0 : keys.length - 1] ?? null;
  return keys[Math.min(keys.length - 1, Math.max(0, at + by))] ?? null;
}
