import { describe, expect, it } from "vitest";
import type { AgentThreadSummary, AgentTurn, Script } from "../../src/api/queries";
import type { Strategy } from "../../src/lib/strategies";
import {
  choiceKind,
  FOLDER_ORDER,
  folderName,
  queuedTurn,
  relativeTime,
  seedFrom,
  suggestions,
  whereLabel,
} from "../../src/lib/threads";

const strategy = (s: Partial<Strategy>): Strategy =>
  ({ strategy_id: "stg_x", name: "x", today_pnl: 0, last_review: null, ...s }) as Strategy;
const script = (s: Partial<Script>): Script =>
  ({ script_id: "scr_x", name: "x.py", last_run: null, ...s }) as Script;

describe("the empty chat's suggestions", () => {
  it("ask about the strategy down most, the latest verdict and a script that stopped badly", () => {
    const found = suggestions(
      [
        strategy({ strategy_id: "a", name: "Straddle", today_pnl: -1200 }),
        strategy({ strategy_id: "b", name: "Fly", today_pnl: -300 }),
        strategy({
          strategy_id: "c",
          name: "Breakout",
          today_pnl: 400,
          last_review: {
            verdict: "not_yet",
            ended_at: "2026-10-09T10:00:00Z",
          } as Strategy["last_review"],
        }),
      ],
      [
        script({ name: "fine.py", last_run: { stop_reason: "exited" } as Script["last_run"] }),
        script({
          script_id: "s2",
          name: "scan.py",
          last_run: { stop_reason: "memory_limit" } as Script["last_run"],
        }),
      ],
    );

    expect(found).toEqual([
      { text: "Why is Straddle down today?", folder: "strategy", subject: "a", where: "Straddle" },
      {
        text: 'What would change the "not yet" verdict on Breakout?',
        folder: "strategy",
        subject: "c",
        where: "Breakout",
      },
      {
        text: "Why did scan.py stop (memory limit)?",
        folder: "script",
        subject: "s2",
        where: "scan.py",
      },
    ]);
  });

  it("fall back to the desk as a whole when nothing in particular stands out", () => {
    expect(suggestions([strategy({ today_pnl: 50 })], [])).toEqual([
      {
        text: "What happened on my desk today?",
        folder: "general",
        subject: null,
        where: "General",
      },
    ]);
  });
});

describe("a new chat from one that can't go on", () => {
  const thread = (t: Partial<AgentThreadSummary>): AgentThreadSummary =>
    ({
      thread_id: "thr_1",
      title: "Why?",
      folder: "general",
      subject: null,
      subject_name: null,
      ...t,
    }) as AgentThreadSummary;

  it("quotes its last answer and files a review's under its strategy", () => {
    const seed = seedFrom(
      thread({
        title: "Review of Straddle",
        folder: "review",
        subject: "stg_1",
        subject_name: "Straddle",
      }),
      "keep: holds up\nafter charges",
    );
    expect(seed).toEqual({
      text: 'Picking up from the chat "Review of Straddle".\n\nIts last answer:\n> keep: holds up\n> after charges\n\n',
      folder: "strategy",
      subject: "stg_1",
      where: "Straddle",
    });
  });

  it("goes to General for a debrief, or a strategy since deleted", () => {
    expect(seedFrom(thread({ folder: "debrief", subject: "2026-10-09" }), null)).toMatchObject({
      text: 'Picking up from the chat "Why?".\n\n',
      folder: "general",
    });
    expect(seedFrom(thread({ folder: "strategy", subject: "stg_gone" }), null).folder).toBe(
      "general",
    );
  });
});

describe("when a chat last moved, as the rail shows it", () => {
  // 11 Oct 2026, 15:00 IST.
  const now = new Date("2026-10-11T09:30:00Z");
  it("reads now, minutes, hours today, a weekday this week, then a date", () => {
    expect(relativeTime("2026-10-11T09:29:31Z", now)).toBe("now");
    expect(relativeTime("2026-10-11T09:18:00Z", now)).toBe("12m");
    expect(relativeTime("2026-10-11T04:00:00Z", now)).toBe("5h");
    expect(relativeTime("2026-10-10T17:00:00Z", now)).toBe("Sat"); // 22:30 IST yesterday
    expect(relativeTime("2026-10-08T05:00:00Z", now)).toBe("Thu");
    expect(relativeTime("2026-10-02T05:00:00Z", now)).toBe("2 Oct");
  });
  it("starts a new day at midnight IST, not UTC", () => {
    // 00:10 IST on the 12th; the chat moved at 23:50 IST on the 11th.
    expect(relativeTime("2026-10-11T18:20:00Z", new Date("2026-10-11T18:40:00Z"))).toBe("20m");
    expect(relativeTime("2026-10-11T16:20:00Z", new Date("2026-10-11T18:40:00Z"))).toBe("Sun");
  });
});

describe("a message waiting for the agent's turn", () => {
  const turn = (status: AgentTurn["job"]["status"], id: string) =>
    ({ job: { job_id: id, status }, steps: [], steps_truncated: false }) as unknown as AgentTurn;

  it("is the pending turn behind a running or stopping one", () => {
    expect(
      queuedTurn([turn("ended", "a"), turn("running", "b"), turn("pending", "c")])?.job.job_id,
    ).toBe("c");
    expect(queuedTurn([turn("stopping", "a"), turn("pending", "b")])?.job.job_id).toBe("b");
  });

  it("isn't a first message, or one the daemon will take next anyway", () => {
    expect(queuedTurn([turn("pending", "a")])).toBeNull();
    expect(queuedTurn([turn("ended", "a"), turn("pending", "b")])).toBeNull();
    expect(queuedTurn([turn("ended", "a")])).toBeNull();
  });
});

describe("the desk manager's chats", () => {
  it("live in a Manager folder that takes the manager's Settings", () => {
    const thread = {
      folder: "manager",
      subject: "2026-09-22",
      subject_name: null,
    } as AgentThreadSummary;
    expect(whereLabel(thread)).toBe("Manager");
    expect(FOLDER_ORDER).toContain("manager");
    expect(folderName("manager")).toBe("Manager");
    expect(choiceKind("manager")).toBe("manager");
  });
});
