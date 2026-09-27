import { describe, expect, test } from "vitest";
import { change, istClock, price, rupees, signed } from "../../src/lib/format";

describe("format", () => {
  test("rupees uses Indian grouping", () => {
    expect(rupees(123456.5)).toBe("₹1,23,456.50");
    expect(rupees(-6975.85, { sign: true })).toBe("-₹6,975.85");
    expect(rupees(6975.85, { sign: true, decimals: 0 })).toBe("+₹6,976");
  });

  test("price groups the Indian way with two decimals", () => {
    expect(price(24812.35)).toBe("24,812.35");
    expect(price(1234567.1)).toBe("12,34,567.10");
  });

  test("signed always carries a sign, hyphen-minus for negatives", () => {
    expect(signed(13.7)).toBe("+13.70");
    expect(signed(-4.25)).toBe("-4.25");
    expect(signed(0)).toBe("0.00");
  });

  test("change matches Kite", () => {
    expect(change(13.7, 0.47)).toBe("+13.70 (+0.47%)");
    expect(change(-95.6, -0.18)).toBe("-95.60 (-0.18%)");
  });

  test("missing values render as —", () => {
    expect(price(null)).toBe("—");
    expect(rupees(undefined)).toBe("—");
    expect(change(null, null)).toBe("—");
  });

  test("istClock shows exchange time whatever the browser's zone", () => {
    expect(istClock(new Date("2026-09-22T06:12:07Z"))).toBe("11:42:07");
  });
});
