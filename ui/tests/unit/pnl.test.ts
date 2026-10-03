import { describe, expect, test } from "vitest";
import { livePrice, markToMarket, total } from "../../src/lib/pnl";

const short = { quantity: -75, average_price: 142.3, last_price: 130 };

describe("pnl", () => {
  test("short position gains when price falls", () => {
    expect(markToMarket(short, 128.1)).toBeCloseTo(1065);
    expect(markToMarket({ ...short, quantity: 10, average_price: 2931.5 }, 2945.2)).toBeCloseTo(
      137,
    );
  });

  test("server figure replaces local after refetch", () => {
    const fetchedAt = 10_000;
    const older = { last_price: 129, received: 5_000 };
    const newer = { last_price: 127, received: 12_000 };
    expect(livePrice(short, fetchedAt, older)).toBe(130);
    expect(livePrice(short, fetchedAt, newer)).toBe(127);
  });

  test("no price means null, not 0", () => {
    expect(markToMarket(short, null)).toBeNull();
    expect(livePrice({ ...short, last_price: null }, 0, undefined)).toBeNull();
    expect(total([10, null])).toBeNull();
    expect(total([10, -4])).toBe(6);
  });
});
