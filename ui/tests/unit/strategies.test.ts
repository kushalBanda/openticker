import { describe, expect, it } from "vitest";
import {
  askedBy,
  contractOf,
  legPnl,
  legText,
  matches,
  optionsLines,
  quickAction,
  type Strategy,
  stateNote,
  when,
} from "../../src/lib/strategies";

const NOW = new Date("2026-09-22T05:00:00Z"); // Tuesday 10:30 IST

function strategy(over: Partial<Strategy>): Strategy {
  return {
    strategy_id: "stg_1",
    name: "NIFTY short straddle",
    kind: "options",
    underlying: "NIFTY 50",
    legs: 2,
    horizon: "intraday",
    locked: false,
    scheduled: false,
    review_scheduled: false,
    updated_at: NOW.toISOString(),
    state: "stopped",
    segments: ["OPT"],
    next_entry: null,
    exit_time: "15:15:00",
    active_run: null,
    pending: null,
    today_pnl: 0,
    net_pnl: 0,
    runs: 0,
    judged_runs: 0,
    wins: 0,
    max_drawdown: 0,
    last_run_at: null,
    has_alert_url: false,
    last_review: null,
    ...over,
  };
}

const run = {
  run_id: "run_1",
  status: "open" as const,
  trigger: "schedule",
  started_at: NOW.toISOString(),
  ended_at: null,
  stop_reason: null,
  stop_detail: null,
  realized_pnl: 0,
  legs: [],
};

describe("a leg's P&L", () => {
  const short = { side: "SELL" as const, quantity: 75, entry_price: 142.3, realized_pnl: 0 };

  it("marks an open short to the tick: it gains as the price falls", () => {
    expect(legPnl({ ...short, status: "open" }, 128.1)).toBeCloseTo(1065);
  });
  it("is the realized figure once closed, whatever the tick", () => {
    expect(legPnl({ ...short, status: "closed", realized_pnl: 420 }, 99)).toBe(420);
  });
  it("is missing, not 0, while an open leg has no price", () => {
    expect(legPnl({ ...short, status: "open" }, null)).toBeNull();
  });
});

describe("filters", () => {
  it("count a signal strategy listening for alerts as running", () => {
    const listening = strategy({ kind: "signal", state: "listening", segments: ["FUT"] });
    expect(matches(listening, "signal", "FUT", "running")).toBe(true);
    expect(matches(listening, "options", "all", "all")).toBe(false);
    expect(matches(listening, "all", "EQ", "all")).toBe(false);
  });
});

describe("what a row says under its state", () => {
  it("names the exit time of a running options strategy", () => {
    expect(stateNote(strategy({ state: "running", active_run: run }), NOW)).toBe("exit 15:15");
  });
  it("names the next entry of a scheduled one by weekday within the week", () => {
    const next = strategy({ state: "scheduled", next_entry: "2026-09-28T09:20:00+05:30" });
    expect(stateNote(next, NOW)).toBe("Mon 09:20");
  });
  it("says a kill is still closing legs", () => {
    expect(stateNote(strategy({ state: "killed", pending: "kill" }), NOW)).toBe("closing legs");
  });
});

describe("a row's one action", () => {
  it("stops a running run, starts an idle options strategy, releases a kill", () => {
    expect(quickAction(strategy({ state: "running", active_run: run }))).toBe("stop");
    expect(quickAction(strategy({ state: "scheduled" }))).toBe("start");
    expect(quickAction(strategy({ state: "killed" }))).toBe("release");
  });
  it("offers nothing while a stop is under way, or to start a signal strategy", () => {
    expect(quickAction(strategy({ state: "running", active_run: run, pending: "stop" }))).toBe(
      null,
    );
    expect(quickAction(strategy({ kind: "signal", state: "stopped" }))).toBe(null);
  });
});

describe("contracts from symbols", () => {
  it("reads options and futures, and leaves stocks alone", () => {
    expect(contractOf("NIFTY29SEP2624800CE")).toEqual({
      type: "CE",
      expiry: "2026-09-29",
      strike: 24800,
    });
    expect(contractOf("NIFTY27OCT26FUT")).toEqual({
      type: "FUT",
      expiry: "2026-10-27",
      strike: null,
    });
    expect(contractOf("RELIANCE").type).toBe("EQ");
  });
});

describe("definitions in words", () => {
  it("says ATM, OTM and ITM for its own option type", () => {
    const leg = { side: "SELL" as const, lots: 1, expiry: "weekly" as const, fixed_strike: null };
    expect(legText({ ...leg, option_type: "CE", strike_offset: 0 })).toBe("Sell CE ATM");
    expect(legText({ ...leg, option_type: "PE", strike_offset: 4 })).toBe("Sell PE OTM 4");
    expect(legText({ ...leg, option_type: "CE", strike_offset: -2 })).toBe("Sell CE ITM 2");
    expect(legText({ ...leg, option_type: "FUT", strike_offset: 0 })).toBe("Sell FUT");
  });
  it("lists only what the definition sets", () => {
    const lines = optionsLines({
      underlying: "NIFTY 50",
      exchange: "NSE",
      horizon: "intraday",
      legs: [
        { side: "SELL", lots: 1, option_type: "CE", expiry: "weekly", strike_offset: 0 },
        { side: "SELL", lots: 1, option_type: "PE", expiry: "weekly", strike_offset: 0 },
      ],
      combined_stop_loss: 3000,
      stops_to_entry_on_leg_stop: false,
      entry_time: "09:20:00",
      exit_time: "15:15:00",
      weekdays: [0, 1, 2, 3, 4],
    } as never);
    expect(lines.map((l) => l.label)).toEqual([
      "Underlying",
      "Expiry",
      "Legs",
      "Lots",
      "Combined stop",
      "Product",
      "Enters",
      "Exits",
    ]);
    expect(lines.find((l) => l.label === "Enters")?.value).toBe("Mon–Fri 09:20");
  });
});

describe("times and who asked", () => {
  it("writes today's time bare and a later date with its month", () => {
    expect(when("2026-09-22T09:20:00+05:30", NOW)).toBe("09:20");
    expect(when("2026-10-05T09:20:00+05:30", NOW)).toBe("5 Oct 09:20");
  });
  it("says how a review came about", () => {
    expect(askedBy("schedule: 20 runs")).toBe("on its schedule");
    expect(askedBy("ui")).toBe("asked by you");
    expect(askedBy("mcp:claude-code")).toBe("asked by Claude");
  });
});
