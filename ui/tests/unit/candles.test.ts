import { describe, expect, test } from "vitest";
import {
  applyTick,
  bucket,
  choiceOf,
  clockSeconds,
  daysBefore,
  fillMarks,
  toWeeks,
} from "../../src/lib/candles";

const utc = (text: string) => Date.parse(`${text}Z`) / 1000;
const five = choiceOf("5minute");

describe("candle times read IST", () => {
  test("an instant becomes its exchange clock time", () => {
    expect(clockSeconds("2026-09-22T10:31:20+05:30")).toBe(utc("2026-09-22T10:31:20"));
  });

  test("candles count from 09:15", () => {
    expect(bucket("2026-09-22T10:31:20+05:30", five)).toBe(utc("2026-09-22T10:30:00"));
    expect(bucket("2026-09-22T10:31:20+05:30", choiceOf("60minute"))).toBe(
      utc("2026-09-22T10:15:00"),
    );
    expect(bucket("2026-09-22T09:15:00+05:30", choiceOf("15minute"))).toBe(
      utc("2026-09-22T09:15:00"),
    );
  });

  test("a day candle is the exchange date", () => {
    expect(bucket("2026-09-22T00:30:00+05:30", choiceOf("day"))).toBe(utc("2026-09-22T00:00:00"));
    expect(bucket("2026-09-21T23:30:00Z", choiceOf("day"))).toBe(utc("2026-09-22T00:00:00"));
  });
});

describe("a tick on the chart", () => {
  const last = { time: utc("2026-09-22T10:30:00"), open: 100, high: 101, low: 99, close: 100.5 };

  test("moves the candle it falls in", () => {
    expect(applyTick(last, 102, "2026-09-22T10:33:00+05:30", five)).toEqual({
      ...last,
      high: 102,
      close: 102,
    });
  });

  test("starts the next candle", () => {
    expect(applyTick(last, 98, "2026-09-22T10:35:01+05:30", five)).toEqual({
      time: utc("2026-09-22T10:35:00"),
      open: 98,
      high: 98,
      low: 98,
      close: 98,
    });
  });

  test("never goes back", () => {
    expect(applyTick(last, 50, "2026-09-22T10:29:00+05:30", five)).toBe(last);
  });
});

test("fills are marked on their candle, one arrow per side", () => {
  const first = utc("2026-09-22T09:15:00");
  const lastBar = utc("2026-09-22T10:30:00");
  const marks = fillMarks(
    [
      { filled_at: "2026-09-22T10:31:00+05:30", side: "BUY", quantity: 10, price: 1 },
      { filled_at: "2026-09-22T10:32:00+05:30", side: "BUY", quantity: 5, price: 1 },
      { filled_at: "2026-09-22T10:32:00+05:30", side: "SELL", quantity: 5, price: 1 },
      { filled_at: "2026-09-21T10:32:00+05:30", side: "SELL", quantity: 5, price: 1 },
    ],
    five,
    first,
    lastBar,
  );
  expect(marks).toEqual([
    { time: lastBar, side: "BUY", text: "B 15" },
    { time: lastBar, side: "SELL", text: "S 5" },
  ]);
});

test("ranges count back calendar days", () => {
  expect(daysBefore("2026-09-22", 14)).toBe("2026-09-08");
});

describe("weeks, from the days", () => {
  const week = choiceOf("week");
  const day = (d: string, o: number, h: number, l: number, c: number) => ({
    time: utc(`${d}T00:00:00`),
    open: o,
    high: h,
    low: l,
    close: c,
  });

  test("a week starts on Monday", () => {
    expect(bucket("2026-09-24T11:00:00+05:30", week)).toBe(utc("2026-09-21T00:00:00")); // Thu
    expect(bucket("2026-09-21T09:15:00+05:30", week)).toBe(utc("2026-09-21T00:00:00")); // Mon
    expect(bucket("2026-09-27T12:00:00+05:30", week)).toBe(utc("2026-09-21T00:00:00")); // Sun
  });

  test("days sum into their week: first open, highest high, lowest low, last close", () => {
    expect(
      toWeeks([
        day("2026-09-18", 10, 12, 9, 11), // Fri
        day("2026-09-21", 11, 15, 10, 14), // Mon
        day("2026-09-22", 14, 16, 8, 9), // Tue
      ]),
    ).toEqual([
      { time: utc("2026-09-14T00:00:00"), open: 10, high: 12, low: 9, close: 11 },
      { time: utc("2026-09-21T00:00:00"), open: 11, high: 16, low: 8, close: 9 },
    ]);
  });

  test("30m candles count from 09:15 too", () => {
    expect(bucket("2026-09-22T10:31:20+05:30", choiceOf("30minute"))).toBe(
      utc("2026-09-22T10:15:00"),
    );
  });
});
