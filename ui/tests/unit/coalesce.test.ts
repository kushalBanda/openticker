import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { coalescer } from "../../src/lib/coalesce";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

test("coalesces_brain_events_into_one_invalidation", () => {
  const run = vi.fn();
  const brain = coalescer(run, 1_500);

  for (let i = 0; i < 20; i++) brain.push(); // a debrief: note, checks, lessons
  vi.advanceTimersByTime(1_499);
  expect(run).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(run).toHaveBeenCalledTimes(1);

  brain.push(); // a later burst refetches again
  vi.advanceTimersByTime(1_500);
  expect(run).toHaveBeenCalledTimes(2);
});

test("cancelled before it runs, it never does", () => {
  const run = vi.fn();
  const brain = coalescer(run, 1_500);
  brain.push();
  brain.cancel();
  vi.advanceTimersByTime(5_000);
  expect(run).not.toHaveBeenCalled();
});
