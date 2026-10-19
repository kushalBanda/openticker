import { describe, expect, it } from "vitest";
import { managerLineText, describe as said, tierOf } from "../../src/lib/events";
import {
  asStop,
  changeText,
  daysBefore,
  deskRoom,
  disagreement,
  effortLevel,
  endedToday,
  isWake,
  type LineChange,
  lineLabel,
  lookTier,
  type ManagerLine,
  market,
  nextLook,
  nowDoing,
  type PlanItem,
  parseRupees,
  planGroups,
  planItemHref,
  planItemLabel,
  railLooks,
  setByLabel,
  spent,
  stepText,
  tableOrder,
  tapeHeights,
  tapeWeeks,
  tapeWindow,
  wakeFacts,
  wakeLabel,
} from "../../src/lib/manager";
import { askedBy, reviewedWhen } from "../../src/lib/strategies";
import type { AuditEntry } from "../../src/stream/connection";

const line = (key: string, name: string | null = null): ManagerLine => ({
  key,
  name,
  capital: null,
  stop: null,
  reason: "why",
  set_by: "manager",
  manager_capital: null,
  manager_stop: null,
  today: null,
  crossed: false,
  set_at: "2026-09-22T09:30:00+05:30",
  triggered_by: "ui",
});

describe("manager lines", () => {
  it("labels desk, own, named and deleted lines", () => {
    expect(lineLabel(line("desk"))).toBe("Desk");
    expect(lineLabel(line("own"))).toBe("Its own trades");
    expect(lineLabel(line("strategy:a", "Straddle"))).toBe("Straddle");
    expect(lineLabel(line("strategy:a"))).toBe("(deleted strategy)");
    expect(lineLabel(line("script:s"))).toBe("(deleted script)");
  });

  it("puts strategies and scripts first, its own trades next, the desk last", () => {
    const order = tableOrder([line("desk"), line("own"), line("strategy:a"), line("script:s")]);
    expect(order.map((l) => l.key)).toEqual(["strategy:a", "script:s", "own", "desk"]);
  });

  it("says who set it", () => {
    expect(setByLabel("you")).toBe("You");
    expect(setByLabel("manager")).toBe("Manager");
  });
});

describe("market and charges", () => {
  it("market counts what's open where it's counted", () => {
    expect(market({ gross: -7015.5, charges: 1587.23, open: -7243.25, net: -15845.98 })).toBe(
      -14258.75,
    );
    expect(market({ gross: 3525, charges: 359.6, open: null, net: 3165.4 })).toBe(3525);
  });

  it("says how a strategy's run ended only when that was today", () => {
    const end = {
      reason: "tick_stale" as const,
      detail: "no price, streamed or quoted, for 60s: X",
      at: "2026-10-14T13:33:05+05:30",
    };
    expect(endedToday(end, "2026-10-14")).toEqual({
      text: "Stopped at 13:33: prices lost",
      fault: true,
    });
    expect(endedToday({ ...end, reason: "schedule" }, "2026-10-14")?.fault).toBe(false);
    expect(endedToday(end, "2026-10-15")).toBeNull();
    expect(endedToday(null, "2026-10-14")).toBeNull();
  });
});

describe("typed amounts", () => {
  it("reads rupees as people type them", () => {
    expect(parseRupees("6,00,000")).toBe(600000);
    expect(parseRupees("₹6,00,000")).toBe(600000);
    expect(parseRupees("-6000")).toBe(-6000);
    expect(parseRupees("6.5L")).toBe(650000);
    expect(parseRupees("5k")).toBe(5000);
    expect(parseRupees("1cr")).toBe(10000000);
    expect(parseRupees("  ")).toBeNull();
    expect(parseRupees("six")).toBeUndefined();
  });

  it("makes a stop a loss", () => {
    expect(asStop(5000)).toBe(-5000);
    expect(asStop(-5000)).toBe(-5000);
  });
});

describe("disagreement", () => {
  it("says what the manager wanted on a line you set", () => {
    const yours = { ...line("desk"), set_by: "you" as const, stop: -5000, manager_stop: -3500 };
    expect(disagreement(yours)).toBe("Manager wanted stop -₹3,500");
  });

  it("is silent on the manager's own lines and when you agree", () => {
    expect(disagreement({ ...line("desk"), manager_stop: -1 })).toBeNull();
    const same = { ...line("desk"), set_by: "you" as const, stop: -1, manager_stop: -1 };
    expect(disagreement(same)).toBeNull();
  });
});

describe("managerLineText", () => {
  it("names who set what", () => {
    const d = {
      key: "strategy:a",
      name: "Straddle",
      capital: 600000,
      stop: -6000,
      set_by: "manager",
    };
    expect(managerLineText(d)).toBe("Manager set Straddle: ₹6,00,000, stop -₹6,000");
    expect(managerLineText({ ...d, key: "desk", set_by: "you", capital: null })).toBe(
      "You set the desk: stop -₹6,000",
    );
  });

  it("says when the manager kept your numbers", () => {
    const d = { key: "own", capital: 300000, stop: null, set_by: "manager", kept_yours: true };
    expect(managerLineText(d)).toBe(
      "Manager kept your numbers for its own trades; it wanted ₹3,00,000, no stop",
    );
  });
});

describe("wakes", () => {
  it("says why it woke, from a reason or a turn's trigger", () => {
    expect(wakeLabel("plan")).toBe("the plan");
    expect(wakeLabel("manager-wake:scheduled")).toBe("its own time");
    expect(wakeLabel("manager-wake:close")).toBe("after the close");
  });

  it("tells a wake from a message the user sent", () => {
    expect(isWake("manager-wake:fallback")).toBe(true);
    expect(isWake("ui")).toBe(false);
  });
});

const entry = (event_type: string, details: Record<string, unknown>): AuditEntry =>
  ({
    id: 1,
    event_type,
    occurred_at: "2026-09-22T10:00:00+05:30",
    triggered_by: null,
    details,
  }) as AuditEntry;

describe("stalled and wake turns", () => {
  it("raises a banner when the manager stalls", () => {
    const stalled = entry("ManagerStalled", { why: "failing", detail: "x", thread_id: "t" });
    expect(tierOf(stalled)).toBe("must-act");
    expect(said(stalled, new Map()).text).toBe("Manager stalled: its turns keep failing");
    const capped = entry("ManagerStalled", { why: "capped", detail: "x", thread_id: null });
    expect(said(capped, new Map()).text).toBe("Manager used its wakes for today");
  });

  it("keeps a finished wake turn out of the toasts, not a failed one or a chat", () => {
    const turn = (reason: string, trigger: string) =>
      entry("AgentJobEnded", { kind: "chat", reason, trigger, thread_id: "t" });
    expect(tierOf(turn("finished", "manager-wake:fallback"))).toBe("record");
    expect(tierOf(turn("failed", "manager-wake:fallback"))).toBe("worth-knowing");
    expect(tierOf(turn("finished", "ui"))).toBe("worth-knowing");
  });
});

describe("reviews the manager asks for", () => {
  it("says the manager judges when, and who asked", () => {
    expect(reviewedWhen(true)).toBe("Reviewed when the manager judges it due");
    expect(reviewedWhen(false)).toBe("Reviewed only when asked");
    expect(askedBy("manager:claude:thr_1")).toBe("asked by the manager");
    expect(askedBy("ui")).toBe("asked by you");
  });
});

describe("how it runs", () => {
  const turn = (status: string, extra: Record<string, unknown> = {}, steps: unknown[] = []) =>
    ({
      job: { status, cost_usd: null, input_tokens: null, output_tokens: null, ...extra },
      steps,
    }) as never;
  const when = (at: string) => at.slice(11, 16);

  it("says what it's doing now", () => {
    expect(nowDoing(true, [turn("pending")], null, when).text).toBe("Waiting to start a look");
    const tool = { kind: "tool", tool: "get_manager", summary: null, text: null };
    expect(nowDoing(true, [turn("running", {}, [tool])], null, when)).toEqual({
      tone: "accent",
      text: "Looking: get_manager",
    });
    expect(nowDoing(true, [turn("ended")], "2026-09-22T11:40:00+05:30", when).text).toBe(
      "Idle until 11:40",
    );
    expect(nowDoing(false, [], null, when).text).toBe("Off: it won't wake on its own");
  });

  it("names a step", () => {
    expect(stepText({ kind: "thinking" } as never)).toBe("thinking");
    expect(stepText({ kind: "tool", tool: "stop_strategy", summary: "Straddle" } as never)).toBe(
      "stop_strategy (Straddle)",
    );
  });

  it("adds up what today's looks used", () => {
    const used = spent([
      turn("ended", { cost_usd: 0.12, input_tokens: 1000, output_tokens: 200 }),
      turn("ended", { cost_usd: null, input_tokens: 500, output_tokens: 0 }),
    ]);
    expect(used).toEqual({ usd: 0.12, tokens: 1700 });
    expect(spent([turn("ended")]).usd).toBeNull();
  });
});

describe("wakeFacts", () => {
  const plan = [
    '<wake reason="plan" day="2026-10-15">',
    '<since_last_close from="Wed 14 Oct 15:30">',
    "- 13:31 The zerodha session expired: live prices stopped.",
    "- 13:31 6 scripts ended: failed: a, b, c and 3 more.",
    "</since_last_close>",
    '<yesterdays_close day="Wed 14 Oct 2026">',
    "Desk ended -₹15,812.",
    "Lines for tomorrow set.",
    "</yesterdays_close>",
    "</wake>",
    "Plan today, Thu 15 Oct 2026. Read the desk.",
  ].join("\n");

  it("reads what broke and the close answer", () => {
    expect(wakeFacts(plan)).toEqual({
      from: "Wed 14 Oct 15:30",
      since: [
        "13:31 The zerodha session expired: live prices stopped.",
        "13:31 6 scripts ended: failed: a, b, c and 3 more.",
      ],
      close: "Desk ended -₹15,812.\nLines for tomorrow set.",
    });
  });

  it("says nothing broke and no close plainly", () => {
    const quiet = plan
      .replace(
        /<since_last_close([^>]*)>[\s\S]*?<\/since_last_close>/,
        "<since_last_close$1>\nNothing broke.\n</since_last_close>",
      )
      .replace(
        /<yesterdays_close([^>]*)>[\s\S]*?<\/yesterdays_close>/,
        "<yesterdays_close$1>\nNo close answer: you weren't on.\n</yesterdays_close>",
      );
    expect(wakeFacts(quiet)).toEqual({ from: "Wed 14 Oct 15:30", since: [], close: null });
  });

  it("is null for a wake with no plan facts", () => {
    expect(
      wakeFacts('<wake reason="scheduled" day="2026-10-15">\n</wake>\nThe time you set came.'),
    ).toBeNull();
    expect(wakeFacts(null)).toBeNull();
  });
});

describe("the day rail", () => {
  const look = (trigger: string, started: string, extra: Record<string, unknown> = {}) =>
    ({
      job: {
        job_id: `job_${started}`,
        trigger,
        status: "ended",
        created_at: started,
        started_at: started,
        model_used: "claude-opus-5-5",
        model: "opus",
        effort: "high",
        cost_usd: 0.26,
        ...extra,
      },
      steps: [],
    }) as never;

  it("places looks on 09:00–15:45 by tier, and the stretch before it was on", () => {
    const { looks, offUntil } = railLooks([
      look("manager-wake:plan", "2026-10-14T13:51:00+05:30"),
      look("ui", "2026-10-14T14:10:00+05:30"), // the user writing: not a look
      look("manager-wake:scheduled", "2026-10-14T14:50:00+05:30", { effort: "low" }),
      look("manager-wake:close", "2026-10-14T15:35:00+05:30"),
    ]);
    expect(looks.map((l) => [l.at, l.pct, l.tier, l.label])).toEqual([
      ["13:51", 71.9, "decisive", "The plan"],
      ["14:50", 86.4, "check", "Its own time"],
      ["15:35", 97.5, "decisive", "After the close"],
    ]);
    expect(looks[0]?.model).toBe("claude-opus-5-5");
    expect(offUntil).toBe(71.9);
  });

  it("was on all day when the plan came before the open", () => {
    const { looks, offUntil } = railLooks([look("manager-wake:plan", "2026-10-14T09:00:00+05:30")]);
    expect(looks[0]?.pct).toBe(0);
    expect(offUntil).toBeNull();
  });

  it("tells the tiers apart", () => {
    expect(lookTier("manager-wake:fallback")).toBe("check");
    expect(lookTier("manager-wake:asked")).toBe("decisive");
    expect(lookTier("ui")).toBeNull();
  });

  it("says when it looks next", () => {
    const at = (iso: string) => new Date(iso);
    expect(nextLook(false, null, null, at("2026-10-14T10:00:00+05:30")).when).toBe("Off");
    expect(
      nextLook(
        true,
        "2026-10-14T11:40:00+05:30",
        "after the 11:30 data.",
        at("2026-10-14T10:00:00+05:30"),
      ),
    ).toEqual({ when: "11:40", why: "after the 11:30 data. Breakages wake it sooner." });
    expect(nextLook(true, null, null, at("2026-10-14T16:00:00+05:30"))).toEqual({
      when: "09:00",
      why: "The plan, 15 minutes before the next open.",
    });
    expect(nextLook(true, null, null, at("2026-10-15T08:00:00+05:30")).why).toBe(
      "The plan, 15 minutes before the open.",
    );
    expect(
      nextLook(true, "2026-10-15T10:00:00+05:30", null, at("2026-10-14T16:00:00+05:30")).when,
    ).toBe("Thu 10:00");
    expect(nextLook(true, null, null, at("2026-10-14T11:00:00+05:30")).when).toBe(
      "Within the hour",
    );
  });

  it("gauges effort over the model's own levels", () => {
    const levels = ["low", "medium", "high", "xhigh", "max"];
    expect(effortLevel(null, levels)).toBe(0);
    expect(effortLevel("low", levels)).toBe(1);
    expect(effortLevel("high", levels)).toBe(3);
    expect(effortLevel("max", levels)).toBe(5);
    expect(effortLevel("high", ["low", "medium", "high"])).toBe(5);
  });
});

describe("the tape of days", () => {
  it("steps back by calendar days", () => {
    expect(daysBefore("2026-10-15", 40)).toBe("2026-09-05");
  });

  it("sizes each day's bar on a square root, never too small to see", () => {
    expect(tapeHeights([-16000, 4000, 100, 0, null])).toEqual([1, 0.5, 0.12, 0, 0]);
    expect(tapeHeights([])).toEqual([]);
    expect(tapeHeights([0, null])).toEqual([0, 0]);
  });

  it("keeps today's window for a day in it, and centres on a day picked before it", () => {
    expect(tapeWindow("2026-10-14", "2026-10-15", 40)).toEqual(["2026-09-05", "2026-10-15"]);
    expect(tapeWindow("2026-08-03", "2026-10-15", 40)).toEqual(["2026-07-14", "2026-08-23"]);
    expect(tapeWindow("2026-08-13", "2026-09-22", 40)).toEqual(["2026-08-13", "2026-09-22"]);
    expect(tapeWindow("2026-08-12", "2026-09-22", 40)).toEqual(["2026-07-23", "2026-09-01"]);
  });

  it("starts a week after a weekend or a skipped week", () => {
    const days = ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-22"];
    expect([...tapeWeeks(days)]).toEqual([2, 4]);
    expect([...tapeWeeks([])]).toEqual([]);
  });
});

describe("a line's change in a phrase", () => {
  const change = (over: Partial<LineChange>): LineChange => ({
    at: "2026-10-14T13:52:00+05:30",
    capital: 200000,
    stop: -6000,
    set_by: "manager",
    kept_yours: false,
    reason: "1.8x its median loser",
    after_close: false,
    ...over,
  });

  it("says what moved, who moved it and why", () => {
    const first = change({});
    expect(changeText(first)).toBe(
      "13:52 stop -₹6,000, capital ₹2,00,000 by the manager: 1.8x its median loser",
    );
    const yours = change({
      at: "2026-10-14T15:36:00+05:30",
      stop: -4000,
      set_by: "you",
      reason: "set by you",
    });
    expect(changeText(yours, first)).toBe("15:36 stop -₹4,000 by you");
  });

  it("leaves out what the day's first change didn't set", () => {
    expect(changeText(change({ capital: null, reason: "" }))).toBe(
      "13:52 stop -₹6,000 by the manager",
    );
  });

  it("marks the manager's wish beside yours and the close look's numbers", () => {
    expect(changeText(change({ kept_yours: true, reason: "" }), change({}))).toBe(
      "13:52 no change wanted by the manager; yours stood",
    );
    expect(changeText(change({ after_close: true, stop: null, reason: "" }), change({}))).toBe(
      "13:52 stop none by the manager, for the next day",
    );
  });
});

describe("the plan (ADR 45)", () => {
  const item = (key: string, call: PlanItem["call"], name: string | null = null): PlanItem => ({
    key,
    name,
    call,
    why: "x",
  });

  it("groups items runs, holds, sits out, each beside its line, leaving empty groups out", () => {
    const line = { key: "strategy:a", stop: -9000 } as ManagerLine;
    const groups = planGroups(
      [item("strategy:b", "sits_out"), item("strategy:a", "holds"), item("own", "sits_out")],
      [line],
    );
    expect(groups.map((g) => [g.call, g.items.map((i) => i.item.key)])).toEqual([
      ["holds", ["strategy:a"]],
      ["sits_out", ["strategy:b", "own"]],
    ]);
    expect(groups[0]?.items[0]?.line).toBe(line);
    expect(planGroups([item("own", "runs")], null)[0]?.items[0]?.line).toBeNull();
  });

  it("names and links an item", () => {
    expect(planItemLabel(item("own", "runs"))).toBe("Its own trades");
    expect(planItemLabel(item("strategy:stg_1", "runs", "Straddle"))).toBe("Straddle");
    expect(planItemLabel(item("script:scr_1", "runs"))).toBe("scr_1");
    expect(planItemHref("strategy:stg_1")).toBe("/strategies/stg_1");
    expect(planItemHref("script:scr_1")).toBe("/scripts/scr_1");
    expect(planItemHref("own")).toBeNull();
  });

  it("gives the desk's room before its stop", () => {
    expect(deskRoom(-16721, -40000)).toEqual({ used: 16721 / 40000, left: 23279 });
    expect(deskRoom(5000, -40000)).toEqual({ used: 0, left: 45000 });
    expect(deskRoom(-50000, -40000)).toEqual({ used: 1, left: 0 });
    expect(deskRoom(-100, null)).toBeNull();
    expect(deskRoom(null, -40000)).toBeNull();
  });
});
