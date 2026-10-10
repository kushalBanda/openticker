import { expect, test } from "vitest";
import {
  dayTitle,
  heldText,
  noteHref,
  OUTCOME,
  pageHref,
  recordHref,
  statusLabel,
  subjectText,
  wikiHref,
} from "../../src/lib/brain";

test("a wikilink goes to the note it names among the links, else nowhere", () => {
  const to = wikiHref([
    { kind: "day", key: "2026-10-05", note_id: "bn_1a2b3c", title: "Mon 5 Oct" },
    { kind: "symbol", key: "NSE:NIFTY 50", note_id: "bn_4d5e6f", title: "NIFTY 50" },
  ]);
  expect(to({ kind: "day", key: "2026-10-05" })).toEqual({
    href: "#bn_1a2b3c",
    title: "Mon 5 Oct",
  });
  expect(to({ kind: "symbol", key: "NSE:NIFTY 50" })?.href).toBe("#bn_4d5e6f");
  expect(to({ kind: "lesson", key: "les_gone" })).toBeNull();
});

test("strategies and symbols lead to their own pages", () => {
  expect(recordHref("strategy", "str_7f3a")).toEqual({
    href: "/strategies/str_7f3a",
    label: "Open strategy",
  });
  expect(recordHref("symbol", "NSE:NIFTY 50")?.href).toBe("/symbols/NSE/NIFTY%2050");
  expect(recordHref("lesson", "les_1")).toEqual({
    href: "/brain/lessons/les_1",
    label: "Open lesson",
  });
  expect(recordHref("proposal", "prp_1")?.href).toBe("/brain/proposals/prp_1");
  expect(recordHref("symbol", "nonsense")).toBeNull();
});

test("held and status words", () => {
  expect(heldText(0, 0)).toBe("Not checked yet");
  expect(heldText(9, 7)).toBe("Held 7 of 9");
  expect(statusLabel("tested")).toBe("Tested");
});

const day = { kind: "day", key: "2026-09-21", note_id: "bn_1", title: "Mon 21 Sep" };
const lesson = { kind: "lesson", key: "les_1", note_id: "les_1", title: "Exit by 11" };

test("a note's own page: a day's, lesson's or proposal's; strategies in the graph", () => {
  expect(noteHref(day)).toBe("/brain/days/2026-09-21");
  expect(noteHref(lesson)).toBe("/brain/lessons/les_1");
  expect(noteHref({ kind: "proposal", key: "prp_1", note_id: "prp_1" })).toBe(
    "/brain/proposals/prp_1",
  );
  expect(noteHref({ kind: "strategy", key: "stg_1", note_id: "bn_9" })).toBe("/brain#bn_9");
  expect(recordHref("day", "2026-09-21")).toEqual({
    href: "/brain/days/2026-09-21",
    label: "Open day",
  });
});

test("off the graph, a wikilink goes to its note's own page, with its title", () => {
  const to = pageHref([day, lesson]);
  expect(to({ kind: "day", key: "2026-09-21" })).toEqual({
    href: "/brain/days/2026-09-21",
    title: "Mon 21 Sep",
  });
  expect(to({ kind: "lesson", key: "les_1" })?.href).toBe("/brain/lessons/les_1");
  expect(to({ kind: "lesson", key: "les_gone" })).toBeNull();
});

test("a day is titled as the server titles it", () => {
  expect(dayTitle("2026-09-21")).toBe("Mon 21 Sep");
  expect(dayTitle("2026-10-05")).toBe("Mon 5 Oct");
  expect(dayTitle("nope")).toBe("nope");
});

test("a check names its run by strategy, or its order, and says how it went", () => {
  const names = new Map([["stg_1", "NIFTY short straddle"]]);
  expect(subjectText({ run_id: "run_1", strategy_id: "stg_1" }, names)).toBe(
    "Run of NIFTY short straddle",
  );
  expect(subjectText({ run_id: "run_2", strategy_id: "stg_gone" }, names)).toBe(
    "Run of a deleted strategy",
  );
  expect(subjectText({ order_id: "SB1" }, names)).toBe("Order SB1 outside a strategy");
  expect(OUTCOME.not_held).toEqual({ label: "Didn't hold", tone: "down" });
  expect(OUTCOME.not_tested?.tone).toBeUndefined();
});
