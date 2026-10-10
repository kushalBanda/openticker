import { describe, expect, test } from "vitest";
import {
  BELL_KINDS,
  brainPageOf,
  byLabel,
  dayOf,
  describe as describeEvent,
  fromDate,
  queriesToInvalidate,
  strategyOf,
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

describe("agent jobs by their title", () => {
  const debrief = {
    kind: "debrief",
    strategy_id: null,
    subject: "2026-10-05",
    title: "Debrief of Mon 5 Oct",
    reason: "finished",
  };

  test("a debrief job is named by its title, opens its day, and refreshes the brain", () => {
    expect(describeEvent(entry("AgentJobEnded", debrief)).text).toBe("Debrief of Mon 5 Oct is in");
    expect(describeEvent(entry("AgentJobEnded", debrief)).kind).toBe("Debrief");
    expect(describeEvent(entry("AgentJobStarted", { ...debrief, harness: "codex" })).text).toBe(
      "Debrief of Mon 5 Oct started (Codex)",
    );
    expect(byLabel(entry("AgentJobEnded", debrief))).toBe("Debrief job");
    expect(dayOf(entry("AgentJobEnded", debrief))).toBe("2026-10-05");
    expect(strategyOf(entry("AgentJobEnded", debrief))).toBeNull();
    expect(queriesToInvalidate(entry("AgentJobEnded", debrief))).toEqual([
      ["agent-jobs"],
      ["brain"],
    ]);
  });

  test("a review job reads as before, older entries without a title too", () => {
    const review = {
      kind: "review",
      strategy_id: "s1",
      strategy_name: "condor",
      reason: "timeout",
    };
    expect(describeEvent(entry("AgentJobEnded", { ...review, detail: "too slow" })).text).toBe(
      "Review of condor ended: too slow",
    );
    expect(
      describeEvent(
        entry("AgentJobEnded", { ...review, title: "Review of condor", reason: "finished" }),
      ).text,
    ).toBe("Review of condor answered");
    expect(byLabel(entry("AgentJobStarted", review))).toBe("Review job");
    expect(dayOf(entry("AgentJobEnded", review))).toBeNull();
  });
});

describe("the brain's events", () => {
  const names = new Map([["stg_1", "NIFTY short straddle"]]);

  test("a debrief: worth knowing when written in a session, a record from its own job", () => {
    const written = entry("DebriefWritten", {
      trading_date: "2026-10-05",
      note_id: "bn_1",
      headline: "Straddle sold into rich IV",
    });
    expect(describeEvent(written).text).toBe("Debrief of Mon 5 Oct: Straddle sold into rich IV");
    expect(tierOf({ ...written, triggered_by: "mcp:claude-code" })).toBe("worth-knowing");
    expect(tierOf({ ...written, triggered_by: "debrief:2026-10-05" })).toBe("record");
    const quiet = entry("DebriefWritten", {
      trading_date: "2026-10-05",
      headline: "No trades",
      quiet: true,
    });
    expect(tierOf(quiet)).toBe("record");
    expect(describeEvent(quiet).text).toBe("Mon 5 Oct was quiet: No trades");
    expect(brainPageOf(written)).toBe("/brain/days/2026-10-05");
  });

  test("a lesson's status moving says from and to, with its checks", () => {
    const moved = entry("LessonStatusChanged", {
      lesson_id: "les_1",
      title: "Exit by 11:00",
      previous: "tested",
      status: "rule",
      held: 8,
      checks: 10,
    });
    expect(describeEvent(moved)).toEqual({
      kind: "Lesson",
      tone: "up",
      text: "Exit by 11:00: tested → rule, held 8 of 10",
    });
    const retired = entry("LessonStatusChanged", {
      title: "Exit by 11:00",
      previous: "hunch",
      status: "retired",
      override: "retired",
      reason: "one day only",
      held: 0,
      checks: 0,
    });
    expect(describeEvent(retired).text).toBe("Exit by 11:00 retired by hand: one day only");
    expect(tierOf(moved)).toBe("worth-knowing");
    expect(brainPageOf(moved)).toBe("/brain/lessons/les_1");
  });

  test("proposals name their strategy; deciding one is a record", () => {
    const raised = entry("ProposalRaised", {
      proposal_id: "prp_1",
      strategy_id: "stg_1",
      change: "Exit by 11:00 on expiry",
    });
    const rejected = entry("ProposalDecided", {
      proposal_id: "prp_1",
      strategy_id: "stg_1",
      change: "Exit by 11:00 on expiry",
      decision: "reject",
      reason: "Keep the theta",
    });
    expect(describeEvent(raised, names).text).toBe(
      "Proposed for NIFTY short straddle: Exit by 11:00 on expiry",
    );
    expect(describeEvent(rejected, names).text).toBe(
      "NIFTY short straddle: Exit by 11:00 on expiry rejected (“Keep the theta”)",
    );
    expect([tierOf(raised), tierOf(rejected)]).toEqual(["worth-knowing", "record"]);
    // Its Open goes to the proposal, not the strategy it names.
    expect(brainPageOf(raised)).toBe("/brain/proposals/prp_1");
  });

  test("every brain event refetches the brain and nothing else; the bell has the worth-knowing ones", () => {
    for (const type of ["DebriefWritten", "LessonWritten", "ProposalRaised", "BrainNoteEdited"]) {
      expect(queriesToInvalidate(entry(type))).toEqual([["brain"]]);
    }
    expect(BELL_KINDS).toEqual(
      expect.arrayContaining(["DebriefWritten", "LessonStatusChanged", "ProposalRaised"]),
    );
    expect(BELL_KINDS).not.toContain("LessonWritten");
  });
});
