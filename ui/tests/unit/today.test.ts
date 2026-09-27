import { describe, expect, test } from "vitest";
import type { Schemas } from "../../src/api/client";
import { dayStats, sinceSentence, tabTitle, weeks } from "../../src/lib/today";

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

test("tab title: the figure, else the page", () => {
  expect(tabTitle(6976.4, "Dashboard")).toBe("+₹6,976 · OpenTicker");
  expect(tabTitle(-12, "Positions")).toBe("-₹12 · Positions");
  expect(tabTitle(null, "Positions")).toBe("Positions · OpenTicker");
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
  ).toEqual({ best: 500, worst: -200, winning: 1, days: 2 });
});
