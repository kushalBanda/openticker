import { describe, expect, it } from "vitest";
import {
  CLOSE,
  istDay,
  istMinutes,
  OPEN,
  sessionAt,
  sessionMinutes,
  toClock,
  toMinutes,
} from "../../src/lib/session";

describe("the exchange's day", () => {
  it("names the exchange-local day of an instant", () => {
    expect(istDay(new Date("2026-10-14T19:00:00Z"))).toBe("2026-10-15"); // 00:30 IST
    expect(istDay("2026-10-15T03:45:00Z")).toBe("2026-10-15");
  });

  it("reads an instant as minutes since midnight, IST", () => {
    expect(istMinutes("2026-10-15T03:45:00Z")).toBe(OPEN); // 09:15 IST
  });

  it("writes and reads clock times", () => {
    expect(toClock(OPEN)).toBe("09:15");
    expect(toMinutes("15:30")).toBe(CLOSE);
  });

  it("lists the session's minutes, open to close inclusive", () => {
    const minutes = sessionMinutes();
    expect(minutes).toHaveLength(CLOSE - OPEN + 1);
    expect(minutes[0]).toBe("09:15");
    expect(minutes.at(-1)).toBe("15:30");
    expect(sessionMinutes(5)[1]).toBe("09:20");
  });

  it("places a minute along the session, held to it", () => {
    expect(sessionAt(OPEN)).toBe(0);
    expect(sessionAt(CLOSE)).toBe(1);
    expect(sessionAt(8 * 60)).toBe(0);
  });
});
