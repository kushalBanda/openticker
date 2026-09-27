import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/api/client";
import { clientLabel, harnessLabel, jobBadge, jobState, took, why } from "../../src/lib/agents";

type Job = Schemas["AgentJobResult"];

const NOW = new Date("2026-09-22T05:00:00Z");

function job(over: Partial<Job>): Job {
  return {
    job_id: "job_1",
    kind: "review",
    strategy_id: "stg_1",
    harness: "claude",
    status: "ended",
    trigger: "ui",
    created_at: NOW.toISOString(),
    started_at: NOW.toISOString(),
    ended_at: NOW.toISOString(),
    end_reason: "finished",
    end_detail: null,
    summary: null,
    verdict: null,
    cost_usd: null,
    ...over,
  } as Job;
}

describe("who's calling", () => {
  it("gives Claude Code and Codex their names, and passes an unknown client's name through", () => {
    expect(clientLabel("claude-code")).toBe("Claude Code");
    expect(clientLabel("codex")).toBe("Codex");
    expect(clientLabel("some-other-client")).toBe("some-other-client");
  });
});

describe("which coding agent runs a job", () => {
  it("is Claude Code unless it says codex", () => {
    expect(harnessLabel("claude")).toBe("Claude Code");
    expect(harnessLabel("codex")).toBe("Codex");
  });
});

describe("a job's state", () => {
  it("is waiting or running from its status, before it ends", () => {
    expect(jobState(job({ status: "pending" }))).toBe("waiting");
    expect(jobState(job({ status: "running" }))).toBe("running");
    expect(jobState(job({ status: "stopping" }))).toBe("stopping");
  });
  it("reads the end reason once it has ended", () => {
    expect(jobState(job({ status: "ended", end_reason: "finished" }))).toBe("finished");
    expect(jobState(job({ status: "ended", end_reason: "stopped" }))).toBe("stopped");
    expect(jobState(job({ status: "ended", end_reason: "daemon_stopped" }))).toBe("stopped");
    expect(jobState(job({ status: "ended", end_reason: "timeout" }))).toBe("timed_out");
    expect(jobState(job({ status: "ended", end_reason: "refused" }))).toBe("refused");
  });
  it("falls back to failed for anything else that ended badly", () => {
    expect(jobState(job({ status: "ended", end_reason: "failed" }))).toBe("failed");
    expect(jobState(job({ status: "ended", end_reason: "start_failed" }))).toBe("failed");
    expect(jobState(job({ status: "ended", end_reason: "lost" }))).toBe("failed");
  });
});

describe("a state's badge", () => {
  it("marks timeouts and failures down, leaves the rest untoned or accented", () => {
    expect(jobBadge("running").tone).toBe("accent");
    expect(jobBadge("timed_out").tone).toBe("down");
    expect(jobBadge("failed").tone).toBe("down");
    expect(jobBadge("finished").tone).toBeUndefined();
  });
});

describe("how long a job took", () => {
  it("is null before it starts", () => {
    expect(took(job({ started_at: null, ended_at: null }), NOW)).toBeNull();
  });
  it("measures against now while running, against its end once ended", () => {
    const started = new Date(NOW.getTime() - 65_000);
    expect(took(job({ started_at: started.toISOString(), ended_at: null }), NOW)).toBe("1m 05s");
    expect(
      took(
        job({
          started_at: started.toISOString(),
          ended_at: new Date(NOW.getTime() - 5_000).toISOString(),
        }),
        NOW,
      ),
    ).toBe("1m 00s");
  });
});

describe("why a job ran", () => {
  it("strips the schedule prefix and keeps its own words", () => {
    expect(why("schedule: 20 runs")).toBe("20 runs");
  });
  it("otherwise says who asked, same as a strategy's askedBy", () => {
    expect(why("ui")).toBe("asked by you");
    expect(why("mcp:claude-code")).toBe("asked by Claude");
  });
});
