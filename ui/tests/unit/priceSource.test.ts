import { describe, expect, test } from "vitest";
import { priceSource } from "../../src/shell/StatusBar";
import type { FeedStatus } from "../../src/stream/connection";

const NOW = new Date("2026-09-22T05:00:00Z");
const status = (over: Partial<FeedStatus>): FeedStatus => ({
  broker: "zerodha",
  broker_connected: true,
  broker_expires_at: "2026-09-23T06:00:00+05:30",
  last_tick_at: null,
  market_open: true,
  state: "live",
  ...over,
});

describe("price source", () => {
  test("live, quiet and closed name the broker", () => {
    expect(priceSource(status({}), "live", NOW)).toEqual({ tone: "up", text: "Zerodha · live" });
    expect(priceSource(status({ state: "quiet" }), "live", NOW).text).toBe("Zerodha · quiet");
    expect(priceSource(status({ state: "closed" }), "live", NOW).text).toBe("Zerodha");
  });

  test("a lost socket reads as reconnecting, whatever the feed said", () => {
    expect(priceSource(status({}), "polling", NOW)).toEqual({
      tone: "warn",
      text: "Zerodha · reconnecting",
    });
  });

  test("an expired session is told apart from no broker at all", () => {
    const expired = status({
      broker_connected: false,
      broker_expires_at: "2026-09-22T06:00:00+05:30",
      state: "no-broker",
    });
    const none = status({ broker_connected: false, broker_expires_at: null, state: "no-broker" });

    expect(priceSource(expired, "live", NOW)).toEqual({
      tone: "down",
      text: "Zerodha expired",
      warn: true,
    });
    expect(priceSource(none, "live", NOW)).toEqual({ tone: "muted", text: "No broker" });
  });
});
