import { describe, expect, test } from "vitest";
import {
  change,
  instrumentName,
  istClock,
  price,
  qty,
  rupees,
  signed,
  sourceLabel,
} from "../../src/lib/format";

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
    expect(signed(-3117)).toBe("-3,117.00");
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

  test("instrumentName prettifies futures, monthly and weekly options", () => {
    expect(instrumentName("RELIANCE", "NSE", "EQ")).toEqual({ name: "RELIANCE", tag: "" });
    expect(instrumentName("RELIANCE", "BSE", "EQ")).toEqual({ name: "RELIANCE", tag: "BSE" });
    expect(instrumentName("NIFTY27OCT26FUT", "NFO", "FUT", "2026-10-27")).toEqual({
      name: "NIFTY OCT FUT",
      tag: "NFO",
    });
    expect(instrumentName("NIFTY29SEP2624800CE", "NFO", "CE", "2026-09-29", 24800).name).toBe(
      "NIFTY SEP 24800 CE",
    );
    expect(instrumentName("NIFTY07OCT2625000CE", "NFO", "CE", "2026-10-07", 25000).name).toBe(
      "NIFTY 7th w OCT 25000 CE",
    );
    expect(instrumentName("NIFTY22SEP2624750.5PE", "NFO", "PE", "2026-09-22", 24750.5).name).toBe(
      "NIFTY 22nd w SEP 24750.50 PE",
    );
  });

  test("qty groups without decimals and keeps the minus", () => {
    expect(qty(-1500)).toBe("-1,500");
    expect(qty(null)).toBe("—");
  });

  test("sourceLabel names who did it", () => {
    expect(sourceLabel("claude-code")).toBe("Claude");
    expect(sourceLabel("you")).toBe("You");
  });
});
