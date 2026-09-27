import { describe, expect, test } from "vitest";
import {
  addPick,
  basketTitle,
  inTheMoney,
  type Leg,
  netPremium,
  type Pick,
  putCallRatio,
} from "../../src/lib/basket";

const pick = (
  symbol: string,
  side: "BUY" | "SELL",
  price: number,
  kind: "CE" | "PE" = "CE",
): Pick => ({
  symbol,
  exchange: "NFO",
  side,
  price,
  lotSize: 75,
  kind,
  strike: 24800,
  expiry: "2026-09-29",
});

describe("picking from the chain", () => {
  test("a new contract is one lot", () => {
    expect(addPick([], pick("A", "SELL", 128.05))).toMatchObject([{ symbol: "A", lots: 1 }]);
  });

  test("the same way again adds a lot at the new price", () => {
    const legs = addPick(addPick([], pick("A", "SELL", 128)), pick("A", "SELL", 127.5));
    expect(legs).toMatchObject([{ lots: 2, price: 127.5, side: "SELL" }]);
  });

  test("the other way takes one off, and the leg goes at none", () => {
    const two = addPick(addPick([], pick("A", "BUY", 10)), pick("A", "BUY", 10));
    expect(addPick(two, pick("A", "SELL", 9))).toMatchObject([{ lots: 1, side: "BUY", price: 10 }]);
    expect(addPick(addPick([], pick("A", "BUY", 10)), pick("A", "SELL", 9))).toEqual([]);
  });

  test("no more than 20 legs", () => {
    let legs: Leg[] = [];
    for (let n = 0; n < 25; n++) legs = addPick(legs, pick(`S${n}`, "BUY", 1));
    expect(legs).toHaveLength(20);
  });
});

test("the mock's iron fly takes in 19,350", () => {
  let legs: Leg[] = [];
  legs = addPick(legs, pick("CE24800", "SELL", 128.05));
  legs = addPick(legs, pick("PE24800", "SELL", 139.2, "PE"));
  legs = addPick(legs, pick("CE25400", "BUY", 3.1));
  legs = addPick(legs, pick("PE24200", "BUY", 6.15, "PE"));
  expect(netPremium(legs)).toBeCloseTo(19350, 6);
  // A future pays no premium.
  expect(netPremium([...legs, { ...pick("FUT", "BUY", 24851), kind: "FUT", lots: 1 }])).toBeCloseTo(
    19350,
    6,
  );
});

test("the tray names the underlying and its expiries", () => {
  const legs = [
    { ...pick("A", "SELL", 1), lots: 1 },
    { ...pick("B", "BUY", 1), lots: 1, expiry: "2026-10-06" },
  ];
  expect(basketTitle("NIFTY", legs)).toBe("NIFTY 29 Sep + 6 Oct");
});

test("put-call ratio over the shown strikes", () => {
  const rows = [
    { call: { open_interest: 100 }, put: { open_interest: 50 } },
    { call: { open_interest: 100 }, put: { open_interest: 166 } },
    { call: null, put: { open_interest: null } },
  ];
  expect(putCallRatio(rows)).toBeCloseTo(1.08);
  expect(putCallRatio([])).toBeNull();
});

test("in the money: a call below the underlying, a put above it", () => {
  expect(inTheMoney("CE", 24700, 24812)).toBe(true);
  expect(inTheMoney("PE", 24700, 24812)).toBe(false);
  expect(inTheMoney("PE", 24850, 24812)).toBe(true);
});
