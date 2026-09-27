import { describe, expect, test } from "vitest";
import type { Trade } from "../../src/api/queries";
import { chargeLines, summarise, tradesCsv } from "../../src/lib/trades";

const fill = (over: Partial<Trade>): Trade => ({
  order_id: "SB1",
  filled_at: "2026-09-22T10:14:31+05:30",
  symbol: "TCS",
  exchange: "NSE",
  side: "SELL",
  quantity: 15,
  price: 4139,
  expected_price: 4139,
  value: 62085,
  charges: 22.6,
  charges_detail: { gst: 3, brokerage: 18.6, stamp_duty: 1 },
  realized_pnl: 2527.5,
  product: "MIS",
  triggered_by: "ui",
  source: "you",
  placed_by: null,
  strategy_id: null,
  run_id: null,
  instrument_type: "EQ",
  expiry: null,
  strike: null,
  lot_size: 1,
  ...over,
});

describe("trades", () => {
  test("the summary counts every fill's charges but realized only where recorded", () => {
    const sum = summarise([
      fill({}),
      fill({ side: "BUY", value: 60000, charges: 10, realized_pnl: 0 }),
      fill({ value: 1000, charges: null, realized_pnl: null }),
    ]);
    expect(sum).toEqual({
      fills: 3,
      turnover: 123085,
      charges: 32.6,
      realized: 2527.5,
      unrecorded: 1,
    });
  });

  test("charges read in contract-note order, GST last", () => {
    expect(chargeLines({ gst: 3, stamp_duty: 1, brokerage: 18.6, new_levy: 0.5 })).toEqual([
      { name: "Brokerage", amount: 18.6 },
      { name: "Stamp duty", amount: 1 },
      { name: "New levy", amount: 0.5 },
      { name: "GST", amount: 3 },
    ]);
  });

  test("CSV leaves what wasn't recorded empty and quotes names with commas", () => {
    const csv = tradesCsv([
      fill({ realized_pnl: null, placed_by: "Trend, fast", source: "strategy" }),
    ]);
    const [head, row] = csv.trim().split("\n");
    expect(head?.split(",")).toContain("realized_pnl");
    expect(row).toBe(
      '2026-09-22T10:14:31+05:30,TCS,TCS,NSE,SELL,15,4139,62085,22.6,,MIS,"Trend, fast",SB1',
    );
  });
});
