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
