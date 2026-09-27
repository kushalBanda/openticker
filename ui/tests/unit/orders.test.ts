import { describe, expect, test } from "vitest";
import { describe as say } from "../../src/components/OrderDialog";
import {
  type Contract,
  type OrderDraft,
  placedBy,
  placedByAny,
  problems,
  productsFor,
  statusLabel,
} from "../../src/lib/orders";

const equity: Contract = { instrument_type: "EQ", lot_size: 1, tick_size: 0.05 };
const future: Contract = { instrument_type: "FUT", lot_size: 75, tick_size: 0.1 };
const draft: OrderDraft = {
  symbol: "RELIANCE",
  exchange: "NSE",
  side: "BUY",
  quantity: 10,
  product: "MIS",
  orderType: "LIMIT",
  price: 2945,
};

describe("order dialog rules", () => {
  test("a limit needs a price on the tick; a market order doesn't", () => {
    expect(problems(draft, equity)).toEqual({});
    expect(problems({ ...draft, price: 2945.03 }, equity)).toEqual({ price: "In steps of 0.05" });
    expect(problems({ ...draft, price: undefined }, equity)).toEqual({ price: "Required" });
    expect(problems({ ...draft, orderType: "MARKET", price: undefined }, equity)).toEqual({});
  });

  test("stop orders need a trigger", () => {
    expect(problems({ ...draft, orderType: "SL-M", price: undefined }, equity)).toEqual({
      triggerPrice: "Required",
    });
    expect(problems({ ...draft, orderType: "SL", triggerPrice: 2940 }, equity)).toEqual({});
  });

  test("F&O quantity is whole lots", () => {
    expect(problems({ ...draft, quantity: 100, price: 24858.2 }, future)).toEqual({
      quantity: "A multiple of the lot, 75",
    });
    expect(problems({ ...draft, quantity: 0 }, equity).quantity).toBe("A whole number above 0");
  });

  test("Kite's products per segment", () => {
    expect(productsFor(equity).map((p) => p.value)).toEqual(["MIS", "CNC"]);
    expect(productsFor(future).map((p) => `${p.label} ${p.value}`)).toEqual([
      "Intraday MIS",
      "Overnight NRML",
    ]);
  });

  test("a result reads as Kite writes it", () => {
    expect(say(draft, "RELIANCE")).toBe("Buy 10 RELIANCE at 2,945.00");
    expect(
      say({ ...draft, side: "SELL", orderType: "SL-M", price: undefined, triggerPrice: 2915 }, "X"),
    ).toBe("Sell 10 X, trigger 2,915.00");
  });
});

describe("order book words", () => {
  test("status as Kite says it", () => {
    const pending = { status: "PENDING", order_type: "SL", triggered: false } as const;
    expect(statusLabel(pending)).toBe("Trigger pending");
    expect(statusLabel({ ...pending, triggered: true })).toBe("Open");
    expect(statusLabel({ ...pending, order_type: "LIMIT" })).toBe("Open");
    expect(statusLabel({ ...pending, status: "FILLED" })).toBe("Complete");
  });

  test("placed by: a name when there is one, else who", () => {
    expect(placedBy({ source: "strategy", placed_by: "NIFTY short straddle" })).toBe(
      "NIFTY short straddle",
    );
    expect(placedBy({ source: "claude-code", placed_by: null })).toBe("Claude");
    expect(placedByAny({ source: "codex" }, "agents")).toBe(true);
    expect(placedByAny({ source: "alert" }, "strategies")).toBe(true);
    expect(placedByAny({ source: "you" }, "scripts")).toBe(false);
  });
});
