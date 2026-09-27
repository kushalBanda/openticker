import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/api/client";
import {
  atLimit,
  duration,
  endText,
  lastRunText,
  memoryText,
  runtime,
  scheduleText,
  scriptState,
  stamp,
  startedBy,
} from "../../src/lib/scripts";

type Script = Schemas["ScriptResult"];
type Run = Schemas["ScriptRunResult"];

const NOW = new Date("2026-09-22T05:00:00Z"); // Tuesday 10:30 IST

function run(over: Partial<Run> = {}): Run {
  return {
    run_id: "run_1",
    status: "running",
    trigger: "schedule",
    started_at: NOW.toISOString(),
    ended_at: null,
    stop_reason: null,
    stop_detail: null,
    exit_code: null,
    peak_memory_mb: null,
    ...over,
  } as Run;
}

function script(over: Partial<Script>): Script {
  return {
    script_id: "scr_1",
    name: "Stop trail",
    sha256: "abc",
    running: false,
    schedule: null,
    last_run: null,
    ...over,
  } as Script;
}

describe("where a script is", () => {
  it("is running while its process is up, unless a stop is asked for", () => {
    expect(scriptState(script({ running: true }))).toBe("running");
    expect(scriptState(script({ running: true }), "stop")).toBe("stopping");
  });
  it("reflects the daemon's own stopping status over a stray start ask", () => {
    expect(scriptState(script({ running: true, last_run: run({ status: "stopping" }) }))).toBe(
      "stopping",
    );
  });
  it("shows starting the moment a start is asked, before the daemon catches up", () => {
    expect(scriptState(script({ running: false }), "start")).toBe("starting");
  });
  it("is never run when there's no last run at all", () => {
    expect(scriptState(script({ running: false, last_run: null }))).toBe("never");
  });
  it("reads the last run's stop reason once stopped", () => {
    expect(scriptState(script({ last_run: run({ stop_reason: "exited" }) }))).toBe("finished");
    expect(scriptState(script({ last_run: run({ stop_reason: "memory_limit" }) }))).toBe("failed");
    expect(scriptState(script({ last_run: run({ stop_reason: "stopped" }) }))).toBe("stopped");
  });
});

describe("why a run ended", () => {
  it("names a clean exit and a killed process by their exit code", () => {
    expect(endText(run({ stop_reason: "failed", exit_code: 1 }))).toBe("exit 1");
    expect(endText(run({ stop_reason: "failed", exit_code: -9 }))).toBe("killed");
  });
  it("falls back to the reason's own words otherwise", () => {
    expect(endText(run({ stop_reason: "memory_limit" }))).toBe("memory limit");
    expect(endText(run({ stop_reason: "schedule" }))).toBe("stopped on schedule");
  });
  it("is blank while still running", () => {
    expect(endText(run({ stop_reason: null }))).toBe("");
  });
});

describe("a schedule in words", () => {
  it("is null when there isn't one", () => {
    expect(scheduleText(null)).toBeNull();
  });
  it("says Mon-Fri for the weekday default, with a stop time when set", () => {
    expect(
      scheduleText({
        start_time: "09:16:00",
        stop_time: null,
        weekdays: [0, 1, 2, 3, 4],
        exchange: "NSE",
      }),
    ).toBe("Mon–Fri 09:16");
    expect(
      scheduleText({
        start_time: "09:16:00",
        stop_time: "15:15:00",
        weekdays: [0, 1, 2, 3, 4],
        exchange: "NSE",
      }),
    ).toBe("Mon–Fri 09:16–15:15");
  });
});

describe("duration and runtime", () => {
  it("formats seconds, minutes and hours", () => {
    expect(duration(42_000)).toBe("42s");
    expect(duration(191_000)).toBe("3m 11s");
    expect(duration((2 * 60 + 26) * 60_000)).toBe("2h 26m");
  });
  it("never goes negative", () => {
    expect(duration(-5_000)).toBe("0s");
  });
  it("measures a running run against now, an ended one against its end", () => {
    const started = new Date(NOW.getTime() - 90_000);
    expect(runtime(run({ started_at: started.toISOString(), ended_at: null }), NOW)).toBe("1m 30s");
    expect(
      runtime(
        run({
          started_at: started.toISOString(),
          ended_at: new Date(NOW.getTime() - 30_000).toISOString(),
        }),
        NOW,
      ),
    ).toBe("1m 00s");
  });
});

describe("a timestamp said the way a person would", () => {
  it("is bare time for today, and marked for yesterday", () => {
    const today = new Date("2026-09-22T04:00:00Z");
    expect(stamp(today.toISOString(), NOW)).toBe("09:30:00");
    const yesterday = new Date("2026-09-21T04:00:00Z");
    expect(stamp(yesterday.toISOString(), NOW)).toBe("yesterday 09:30");
  });
  it("gives the date for anything older", () => {
    expect(stamp("2026-09-10T04:00:00Z", NOW)).toBe("10 Sep 09:30");
  });
});

describe("a script's last run, in one line", () => {
  it("says since it started while it runs, and how it ended once it has", () => {
    expect(lastRunText(run({ started_at: NOW.toISOString(), ended_at: null }), NOW)).toBe(
      "since 10:30:00",
    );
    expect(
      lastRunText(
        run({ started_at: NOW.toISOString(), ended_at: NOW.toISOString(), stop_reason: "exited" }),
        NOW,
      ),
    ).toBe("10:30:00, exit 0");
  });
  it("is null when it has never run", () => {
    expect(lastRunText(null, NOW)).toBeNull();
  });
});

describe("peak memory against the limit", () => {
  it("shows the limit only when there is one", () => {
    expect(memoryText(84, 256)).toBe("84 / 256 MB");
    expect(memoryText(84, undefined)).toBe("84 MB");
  });
  it("is null before anything has been recorded", () => {
    expect(memoryText(null, 256)).toBeNull();
    expect(memoryText(undefined, 256)).toBeNull();
  });
  it("is at limit only once the peak reaches it", () => {
    expect(atLimit(256, 256)).toBe(true);
    expect(atLimit(255, 256)).toBe(false);
    expect(atLimit(null, 256)).toBe(false);
    expect(atLimit(300, undefined)).toBe(false);
  });
});

describe("who started a run", () => {
  it("names the schedule, a restart, you, or an agent by name", () => {
    expect(startedBy("schedule")).toBe("its schedule");
    expect(startedBy("recovery")).toBe("a restart");
    expect(startedBy("ui")).toBe("you");
    expect(startedBy("mcp:claude-code")).toBe("Claude");
    expect(startedBy("mcp:codex")).toBe("Codex");
    expect(startedBy("mcp:something-else")).toBe("an agent");
  });
  it("names a REST key by what follows it, else the trigger itself", () => {
    expect(startedBy("rest:key_abc")).toBe("key key_abc");
    expect(startedBy("mystery")).toBe("mystery");
  });
});
