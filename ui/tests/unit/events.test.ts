import { describe, expect, test } from "vitest";
import {
  byLabel,
  describe as describeEvent,
  fromDate,
  queriesToInvalidate,
  tierOf,
} from "../../src/lib/events";
import type { AuditEntry } from "../../src/stream/connection";

const entry = (
  event_type: string,
  details: Record<string, unknown> = {},
  source: AuditEntry["source"] = "system",
  triggered_by: string | null = null,
): AuditEntry => ({
  id: 1,
  occurred_at: "2026-09-22T11:31:02+05:30",
  event_type,
  triggered_by,
  source,
  details,
});

describe("event tiers", () => {
  test("kill and session-expired are must-act", () => {
    expect(tierOf(entry("StrategyStopped", { reason: "kill" }))).toBe("must-act");
    expect(tierOf(entry("StrategyStopped", { reason: "daily_loss_limit" }))).toBe("must-act");
    expect(tierOf(entry("BrokerSessionExpired", { broker: "zerodha" }))).toBe("must-act");
  });

  test("fills and ordinary stops are worth-knowing; placing and syncing are records", () => {
    expect(tierOf(entry("OrderFilled"))).toBe("worth-knowing");
    expect(tierOf(entry("StrategyStopped", { reason: "combined_target" }))).toBe("worth-knowing");
    expect(tierOf(entry("OrderPlaced"))).toBe("record");
    expect(tierOf(entry("InstrumentSyncCompleted"))).toBe("record");
  });

  test("fills invalidate the account and the Dashboard's figures", () => {
    expect(queriesToInvalidate(entry("OrderFilled"))).toEqual([
      ["orders"],
      ["positions"],
      ["funds"],
      ["trades"],
      ["today"],
      ["setup"],
      ["pnl-history"],
      ["charges-summary"],
    ]);
    expect(queriesToInvalidate(entry("StrategyStopped", { strategy_id: "s1" }))).toContainEqual([
      "ledger",
      "s1",
    ]);
  });
});

describe("event text", () => {
  test("a fill says side, quantity, contract and price, by who", () => {
    const fill = entry(
      "OrderFilled",
      { side: "BUY", quantity: 75, symbol: "NIFTY27OCT26FUT", price: 24861 },
      "alert",
      "alert:s2",
    );

    expect(describeEvent(fill)).toEqual({
      kind: "Fill",
      tone: "up",
      text: "Buy 75 NIFTY OCT FUT at 24,861.00",
    });
    expect(byLabel(fill, new Map([["s2", "NIFTY futures trend"]]))).toBe(
      "Alert → NIFTY futures trend",
    );
  });

  test("a kill names the strategy and why", () => {
    const kill = entry(
      "StrategyStopped",
      { strategy_id: "s1", name: "SBIN mean reversion", reason: "kill", detail: "killed by you" },
      "strategy",
      "strategy:s1",
    );

    expect(describeEvent(kill).text).toBe("SBIN mean reversion killed: killed by you");
    expect(describeEvent(kill).kind).toBe("Kill");
    expect(byLabel(kill)).toBe("SBIN mean reversion");
  });

  test("Claude and Codex are named; the server is OpenTicker", () => {
    expect(byLabel(entry("OrderFilled", {}, "claude-code", "mcp:claude-code"))).toBe("Claude");
    expect(byLabel(entry("OrderCancelled"))).toBe("OpenTicker");
  });
});

describe("periods", () => {
  test("count exchange-local days back from now", () => {
    const late = new Date("2026-09-22T20:00:00Z"); // 01:30 IST on the 23rd
    expect(fromDate("today", late)).toBe("2026-09-23");
    expect(fromDate("7d", late)).toBe("2026-09-17");
    expect(fromDate("30d", late)).toBe("2026-08-25");
  });
});

describe("settings events", () => {
  test("logins, resets and charge checks are records the bell doesn't count", () => {
    for (const type of [
      "BrokerConnected",
      "BrokerDisconnected",
      "PaperAccountReset",
      "ChargeRatesChecked",
    ]) {
      expect(tierOf(entry(type))).toBe("record");
    }
  });

  test("a reset, a login and a logout refetch everything", () => {
    expect(queriesToInvalidate(entry("PaperAccountReset"))).toEqual([[]]);
    expect(queriesToInvalidate(entry("BrokerConnected"))).toEqual([[]]);
    expect(queriesToInvalidate(entry("BrokerDisconnected"))).toEqual([[]]);
  });

  test("they read as one line", () => {
    expect(describeEvent(entry("BrokerConnected", { broker: "zerodha" })).text).toBe(
      "Zerodha connected",
    );
    expect(
      describeEvent(entry("PaperAccountReset", { capital: 2500000, orders: 7, trades: 5 })).text,
    ).toBe("Paper account reset to ₹25,00,000.00: 7 orders, 5 trades deleted");
    expect(
      describeEvent(entry("ChargeRatesChecked", { broker: "zerodha", differing: 0, checked: 16 }))
        .text,
    ).toBe("Charges checked: 16 orders match Zerodha's contract note");
  });
});
