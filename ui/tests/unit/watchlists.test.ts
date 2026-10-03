import { describe, expect, test } from "vitest";
import { moved, pickList, step } from "../../src/lib/watchlists";
import type { Tick } from "../../src/stream/connection";

const tick = (last: number, change: number | null, pct: number | null): Tick => ({
  exchange: "NSE",
  symbol: "RELIANCE",
  last_price: last,
  change,
  change_pct: pct,
  as_of: "2026-09-28T10:30:00+05:30",
  streamed: true,
});

describe("a row's change", () => {
  test("the tick's own change wins", () => {
    expect(moved(tick(2945.2, 13.7, 0.47), { last_price: 2940, prev_close: 2900 })).toEqual({
      last: 2945.2,
      change: 13.7,
      pct: 0.47,
    });
  });

  test("worked out from the quote's previous close when the tick has none", () => {
    const got = moved(tick(110, null, null), { last_price: 105, prev_close: 100 });
    expect(got.last).toBe(110);
    expect(got.change).toBeCloseTo(10);
    expect(got.pct).toBeCloseTo(10);
  });

  test("missing, never zero, without a previous close", () => {
    expect(moved(undefined, { last_price: 105, prev_close: null })).toEqual({
      last: 105,
      change: null,
      pct: null,
    });
    expect(moved(undefined, undefined)).toEqual({ last: null, change: null, pct: null });
  });
});

describe("which list shows", () => {
  const lists = [{ watchlist_id: "a" }, { watchlist_id: "b" }];
  test("the one asked for, else the first", () => {
    expect(pickList(lists, "b")?.watchlist_id).toBe("b");
    expect(pickList(lists, "gone")?.watchlist_id).toBe("a");
    expect(pickList([], "a")).toBeUndefined();
  });
});

describe("arrow keys move the selection", () => {
  const keys = ["a", "b", "c"];
  test("down from nothing is the first, up the last", () => {
    expect(step(keys, null, 1)).toBe("a");
    expect(step(keys, null, -1)).toBe("c");
  });
  test("stays in range", () => {
    expect(step(keys, "c", 1)).toBe("c");
    expect(step(keys, "a", -1)).toBe("a");
    expect(step(keys, "b", 1)).toBe("c");
  });
  test("a row gone is like none", () => {
    expect(step(keys, "z", 1)).toBe("a");
    expect(step([], "a", 1)).toBeNull();
  });
});
