import { describe, expect, test } from "vitest";
import type { Schemas } from "../../src/api/client";
import { dayStats, pnlCandles, sinceSentence, weeks } from "../../src/lib/today";

type Entry = Schemas["AuditEntryResult"];

const at = "2026-09-22T11:02:00+05:30";
let id = 0;
const entry = (event_type: string, details: Record<string, unknown>): Entry => ({
  id: ++id,
  occurred_at: "2026-09-22T11:10:00+05:30",
  event_type,
  triggered_by: null,
  source: "system",
  details,
});
const since = (over: Partial<Schemas["SinceResult"]> = {}): Schemas["SinceResult"] => ({
  at,
  fills: 0,
  events: [],
  more_events: 0,
  pnl_change: null,
  ...over,
});

describe("since you were here", () => {
  test("nothing happened", () => {
    expect(sinceSentence(since({ pnl_change: 12 }))).toEqual({
      lead: "Nothing's changed since 11:02.",
      parts: [],
    });
  });

  test("fills, a kill with the strategy's name, then the change", () => {
    const kill = entry("StrategyStopped", { strategy_id: "s1", reason: "kill" });
    const { lead, parts } = sinceSentence(
      since({ fills: 3, events: [kill], pnl_change: -2140 }),
      new Map([["s1", "SBIN mean reversion"]]),
    );
    expect(lead).toBe("Since you were here at 11:02: ");
    expect(parts.map((p) => p.text)).toEqual([
      "3 fills",
      "SBIN mean reversion was killed",
      "you're -₹2,140.00",
    ]);
    expect(parts[1]?.to).toBe("/strategies/s1");
    expect(parts[2]?.tone).toBe("down");
  });

  test("the same refusal twice is said once, counted", () => {
    const refused = () => entry("OrderFailed", { symbol: "NIFTY25OCTFUT" });
    const { parts } = sinceSentence(since({ events: [refused(), refused()] }));
    expect(parts).toHaveLength(1);
    expect(parts[0]?.text).toMatch(/^2 orders for .+ were refused$/);
  });

  test("what isn't named is counted", () => {
    const { parts } = sinceSentence(since({ fills: 1, more_events: 4 }));
    expect(parts.map((p) => [p.text, p.to])).toEqual([
      ["1 fill", "/trades"],
      ["4 more", "/activity"],
    ]);
  });
});

test("calendar weeks run Monday to Friday, blank outside the range", () => {
  const grid = weeks(
    [{ date: "2026-09-22", net: 500, estimated: false }],
    "2026-09-22",
    "2026-09-24",
  );
  expect(grid).toHaveLength(1);
  expect(grid[0]?.map((d) => d?.date ?? null)).toEqual([
    null,
    "2026-09-22",
    "2026-09-23",
    "2026-09-24",
    null,
  ]);
  expect(grid[0]?.[1]?.net).toBe(500);
  expect(grid[0]?.[2]?.net).toBeNull();
});

test("day stats count only days with a figure", () => {
  expect(dayStats([{ date: "2026-09-22", net: null, estimated: false }])).toBeNull();
  expect(
    dayStats([
      { date: "2026-09-22", net: 500, estimated: false },
      { date: "2026-09-23", net: -200, estimated: true },
      { date: "2026-09-24", net: null, estimated: false },
    ]),
  ).toEqual({
    best: 500,
    worst: -200,
    winning: 1,
    days: 2,
    total: 300,
    average: 150,
    month: 300,
    streak: -1,
  });
  expect(
    dayStats([
      { date: "2026-09-29", net: -50, estimated: false },
      { date: "2026-09-30", net: 100, estimated: false },
      { date: "2026-10-01", net: 40, estimated: false },
    ]),
  ).toMatchObject({ month: 40, streak: 2 });
  expect(dayStats([{ date: "2026-10-01", net: 0, estimated: false }])).toMatchObject({
    streak: 0,
  });
});

describe("pnlCandles", () => {
  const p = (minute: string, net_pnl: number) => ({ minute, net_pnl });

  test("five minutes a candle from 09:15, high and low from the points", () => {
    const candles = pnlCandles([
      p("09:15", 0),
      p("09:16", 120),
      p("09:17", -40),
      p("09:19", 60),
      p("09:20", 80),
      p("09:23", 30),
    ]);
    expect(candles).toEqual([
      { slot: "09:15", open: 0, high: 120, low: -40, close: 60 },
      { slot: "09:20", open: 60, high: 80, low: 30, close: 30 },
    ]);
  });

  test("a candle after a gap opens at its own first point", () => {
    const candles = pnlCandles([p("09:15", 10), p("12:01", -200), p("12:03", -150)]);
    expect(candles[1]).toEqual({ slot: "12:00", open: -200, high: -150, low: -200, close: -150 });
  });

  test("a candle that follows opens where the last closed, even below its own points", () => {
    const [, second] = pnlCandles([p("09:15", -500), p("09:20", 100)]);
    expect(second).toEqual({ slot: "09:20", open: -500, high: 100, low: -500, close: 100 });
  });

  test("nothing before the open, nothing at all", () => {
    expect(pnlCandles([p("09:10", 5)])).toEqual([]);
    expect(pnlCandles([])).toEqual([]);
  });
});
