import { expect, test } from "@playwright/test";
import { nextLink } from "./links";

// Ticks never cost a frame (DESIGN.md, the launch bar): on each screen that
// shows live prices, with the fake feed walking every price, three seconds of
// frames are timed in the page. At 60 fps a frame is 16.7 ms; one over 50 ms
// is late, and a long task over 100 ms (script holding the page) is a stutter
// anyone would see.
// A second of each screen's Chrome trace is kept (test-results/traces/), to
// open in DevTools' Performance panel.

const SCREENS = [
  "/",
  "/manager",
  "/watchlist",
  "/options",
  "/positions",
  "/orders",
  "/strategies",
  "/symbols/NSE/RELIANCE",
];

interface Frames {
  frames: number;
  slow: number;
  worst: number;
  /** The longest long task, ms (0: none over 50 ms). */
  longest: number;
}

test("every live screen holds 60 fps while prices tick", async ({ page, browser }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await expect(page.getByTestId("price-source")).toHaveText(/live/, { timeout: 5_000 });

  const results: Record<string, Frames> = {};
  for (const path of SCREENS) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 5_000 });
    await page.waitForTimeout(1_000); // first paint, charts drawn once, reveals done
    results[path] = await page.evaluate(
      () =>
        new Promise<Frames>((resolve) => {
          let longest = 0;
          const observer = new PerformanceObserver((list) => {
            for (const task of list.getEntries()) longest = Math.max(longest, task.duration);
          });
          observer.observe({ type: "longtask" });
          const gaps: number[] = [];
          let last = performance.now();
          const end = last + 3_000;
          const frame = (now: number) => {
            gaps.push(now - last);
            last = now;
            if (now < end) requestAnimationFrame(frame);
            else {
              observer.disconnect();
              resolve({
                frames: gaps.length,
                slow: gaps.filter((g) => g > 50).length,
                worst: Math.round(Math.max(...gaps)),
                longest: Math.round(longest),
              });
            }
          };
          requestAnimationFrame(frame);
        }),
    );
  }

  // Traces after all the timing: tracing, and writing a trace out, cost frames.
  for (const path of SCREENS) {
    await page.goto(path);
    await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 5_000 });
    await page.waitForTimeout(1_000);
    const name = path === "/" ? "dashboard" : path.slice(1).replaceAll("/", "-");
    await browser.startTracing(page, { path: `test-results/traces/${name}.json` });
    await page.waitForTimeout(1_000);
    await browser.stopTracing();
  }
  console.log(JSON.stringify(results, null, 1));
  for (const [path, r] of Object.entries(results)) {
    // ~180 frames in 3 s. Headless Chrome draws in software, and on a busy
    // laptop it misses a frame now and then on any screen, with no script or
    // fetch behind it (measured: 0-2 per run, a different screen each time);
    // the page's own work never holds it past 100 ms.
    expect
      .soft({ path, fps: r.frames / 3 >= 55, late: r.slow <= 2, stutter: r.longest > 100 })
      .toEqual({ path, fps: true, late: true, stutter: false });
  }
});

/** A brain of `count` notes: strategies with their symbols, days, lessons and proposals linked among them. */
function bigBrain(count: number) {
  const kinds = ["day", "lesson", "symbol", "proposal", "strategy"] as const;
  const notes = Array.from({ length: count }, (_, i) => {
    const kind = kinds[i % 10 === 0 ? 4 : i % 4] ?? "day";
    return {
      note_id: `n${i}`,
      kind,
      key: `k${i}`,
      title: `${kind} note ${i} with a longer title`,
      status: kind === "lesson" ? (["hunch", "tested", "rule"][i % 3] ?? null) : null,
      net: kind === "day" ? ((i * 37) % 200) - 100 : null,
    };
  });
  let seed = 7;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const strategies = notes.filter((n) => n.kind === "strategy");
  const links = notes.flatMap((n, i) => {
    if (n.kind === "strategy") return [];
    const to = strategies[Math.floor(rand() * strategies.length)] as { note_id: string };
    const out = [{ from_id: n.note_id, to_id: to.note_id }];
    if (i % 3 === 0) out.push({ from_id: n.note_id, to_id: `n${Math.floor(rand() * count)}` });
    return out.filter((l) => l.from_id !== l.to_id);
  });
  return { notes, links, truncated: false, notice: "" };
}

test("the Brain page holds 60 fps with 1,000 notes while the pointer moves over it", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  const brain = bigBrain(1000);
  await page.route("**/api/v1/brain/graph*", (route) => route.fulfill({ json: brain }));
  await page.goto("/brain");
  await expect(page.getByTestId("graph-count")).toHaveText(/^1000 notes/);
  await page.waitForTimeout(1_500); // opened still, then the layout's last settle
  const opening = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        new PerformanceObserver((list) =>
          resolve(Math.round(Math.max(0, ...list.getEntries().map((t) => t.duration)))),
        ).observe({ type: "longtask", buffered: true });
        setTimeout(() => resolve(0), 200);
      }),
  );
  console.log("brain at 1,000 notes, longest task while opening (ms):", opening);
  expect(opening, "opening 1,000 notes holds the page under 300 ms").toBeLessThan(300);

  const box = await page.getByTestId("brain-graph").boundingBox();
  if (!box) throw new Error("no graph");
  const timing = page.evaluate(
    () =>
      new Promise<Frames>((resolve) => {
        let longest = 0;
        const observer = new PerformanceObserver((list) => {
          for (const task of list.getEntries()) longest = Math.max(longest, task.duration);
        });
        observer.observe({ type: "longtask" });
        const gaps: number[] = [];
        let last = performance.now();
        const end = last + 3_000;
        const frame = (now: number) => {
          gaps.push(now - last);
          last = now;
          if (now < end) requestAnimationFrame(frame);
          else {
            observer.disconnect();
            resolve({
              frames: gaps.length,
              slow: gaps.filter((g) => g > 50).length,
              worst: Math.round(Math.max(...gaps)),
              longest: Math.round(longest),
            });
          }
        };
        requestAnimationFrame(frame);
      }),
  );
  // Sweep the pointer across the graph: every point it crosses fades the rest.
  for (let step = 0; step < 60; step++) {
    await page.mouse.move(box.x + 60 + step * 12, box.y + 120 + (step % 20) * 14);
    await page.waitForTimeout(40);
  }
  const r = await timing;
  console.log("brain at 1,000 notes", JSON.stringify(r));
  expect({ fps: r.frames / 3 >= 55, late: r.slow <= 2, stutter: r.longest > 100 }).toEqual({
    fps: true,
    late: true,
    stutter: false,
  });
});

/** A chat of `count` turns, each with its steps folded and a long Markdown answer. */
function longThread(count: number) {
  const at = "2026-10-11T10:00:00Z";
  const turns = Array.from({ length: count }, (_, i) => ({
    job: {
      job_id: `job_${i}`,
      kind: "chat",
      title: "Chat",
      strategy_id: null,
      subject: null,
      harness: "claude",
      status: "ended",
      trigger: "ui",
      created_at: at,
      started_at: at,
      ended_at: at,
      end_reason: "finished",
      end_detail: "exited with code 0",
      summary: null,
      verdict: null,
      cost_usd: 0.04,
      thread_id: "thr_long",
      prompt: `Question ${i}: how did the straddle do on expiry day ${i}?`,
      model: "opus",
      effort: "high",
      model_used: "claude-opus-5-5",
      input_tokens: 30_000 + i,
      output_tokens: 900,
      duration_ms: 41_000,
    },
    steps: [
      ...Array.from({ length: 12 }, (_, n) => ({
        kind: "tool",
        at: null,
        text: null,
        tool: "get_strategy_runs",
        summary: `strategy_id=stg_${n}, limit=20`,
        result: "20 runs",
        failed: false,
      })),
      {
        kind: "text",
        at: null,
        text: `## Expiry day ${i}\n\n${"The straddle lost ₹1,240 after charges when INDIA VIX opened high. ".repeat(8)}\n\n- one\n- two\n- three`,
        tool: null,
        summary: null,
        result: null,
        failed: false,
      },
    ],
    steps_truncated: false,
  }));
  return {
    thread_id: "thr_long",
    title: "A long chat",
    folder: "general",
    subject: null,
    subject_name: null,
    harness: "claude",
    last_status: "ended",
    updated_at: at,
    continuable: true,
    origin_job_id: null,
    turns,
  };
}

test("a chat of 60 turns holds 60 fps while it scrolls", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await page.route("**/api/v1/agent-threads/thr_long", (route) =>
    route.fulfill({ json: longThread(60) }),
  );
  await page.goto("/agents/thr_long");
  await expect(page.getByRole("heading", { name: "A long chat" })).toBeVisible();
  await page.waitForTimeout(1_000);
  const scroller = page.locator(".aw-scroll");
  const box = await scroller.boundingBox();
  if (!box) throw new Error("no thread");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const timing = page.evaluate(
    () =>
      new Promise<Frames>((resolve) => {
        let longest = 0;
        const observer = new PerformanceObserver((list) => {
          for (const task of list.getEntries()) longest = Math.max(longest, task.duration);
        });
        observer.observe({ type: "longtask" });
        const gaps: number[] = [];
        let last = performance.now();
        const end = last + 3_000;
        const frame = (now: number) => {
          gaps.push(now - last);
          last = now;
          if (now < end) requestAnimationFrame(frame);
          else {
            observer.disconnect();
            resolve({
              frames: gaps.length,
              slow: gaps.filter((g) => g > 50).length,
              worst: Math.round(Math.max(...gaps)),
              longest: Math.round(longest),
            });
          }
        };
        requestAnimationFrame(frame);
      }),
  );
  for (let step = 0; step < 60; step++) {
    await page.mouse.wheel(0, step < 30 ? 400 : -400);
    await page.waitForTimeout(40);
  }
  const r = await timing;
  console.log("a chat of 60 turns", JSON.stringify(r));
  expect({ fps: r.frames / 3 >= 55, late: r.slow <= 2, stutter: r.longest > 100 }).toEqual({
    fps: true,
    late: true,
    stutter: false,
  });
});
