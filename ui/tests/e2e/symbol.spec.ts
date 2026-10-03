import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// One instrument's page over e2e_server.py's account: RELIANCE, which the
// web app bought 10 of (MIS) and a script guards with a stop. The fake
// broker gives it a year of candles and five levels of depth.

const RELIANCE = "/symbols/NSE/RELIANCE";

async function signIn(page: Page) {
  await page.goto(nextLink());
}

const noOverflow = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .stat, .statusbar")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

test("proof: a price moves within 1 s of opening the page", async ({ page }) => {
  await signIn(page);
  await page.goto("/"); // the app is loaded; now open the page as a click would
  await page.waitForLoadState("networkidle");
  const moved = await page.evaluate(async (path) => {
    const opened = performance.now();
    history.pushState({}, "", path);
    dispatchEvent(new PopStateEvent("popstate"));
    const seen: { value: string; at: number }[] = [];
    return await new Promise<{ first: number; moved: number }>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`no move: ${JSON.stringify(seen)}`)), 5000);
      const poll = () => {
        const value = document
          .querySelector('[data-testid="ltp-value"]')
          ?.getAttribute("data-value");
        if (value && seen.at(-1)?.value !== value)
          seen.push({ value, at: performance.now() - opened });
        const [first, second] = seen;
        if (first && second) {
          clearTimeout(timer);
          resolve({ first: first.at, moved: second.at });
        } else requestAnimationFrame(poll);
      };
      poll();
    });
  }, RELIANCE);
  console.log(
    `LTP shown after ${Math.round(moved.first)} ms, moved after ${Math.round(moved.moved)} ms`,
  );
  expect(moved.moved).toBeLessThan(1000);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("RELIANCE");

  // The chart follows the same ticks: its last candle closes at the LTP.
  const chart = page.getByTestId("candle-chart");
  await expect(chart).toBeVisible();
  await expect(async () => {
    const close = await chart.getAttribute("data-last-close");
    const ltp = await page.getByTestId("ltp-value").getAttribute("data-value");
    expect(Number(close)).toBeCloseTo(Number(ltp), 2);
  }).toPass({ timeout: 3000 });
});

test("quote, depth, your fills and your position", async ({ page }) => {
  await signIn(page);
  await page.goto(RELIANCE);
  await expect(page.getByText("NSE · Lot 1 · Tick 0.05")).toBeVisible();
  // 10 MIS from the seed, unless the Positions spec closed it first.
  await expect(page.getByTestId("your-position")).toContainText(/10 · MIS|Nothing open/);
  await expect(page.getByTestId("ltp")).toContainText(/Prev|[+-]\d/);

  const depth = page.getByRole("table", { name: "Market depth" });
  await expect(depth.getByRole("row")).toHaveCount(6); // head + five levels
  await expect(depth).not.toContainText("—");

  const chart = page.getByTestId("candle-chart");
  await expect(chart).toHaveAttribute("data-marks", /^[1-9]/); // the buy of 10 today
  await page
    .getByRole("group", { name: "Interval" })
    .getByRole("button", { name: "1h", exact: true })
    .click();
  await expect(chart).toHaveAttribute("data-marks", /^[1-9]/);
  await page.reload();
  await expect(
    page.getByRole("group", { name: "Interval" }).getByRole("button", { name: "1h", exact: true }),
  ).toHaveAttribute("aria-pressed", "true"); // remembered
  // 30m from the broker; 1W summed from its days. The live price moves the last candle of each.
  for (const label of ["30m", "1W"]) {
    await page
      .getByRole("group", { name: "Interval" })
      .getByRole("button", { name: label, exact: true })
      .click();
    await expect(page.getByText(`NSE · ${label} · IST`)).toBeVisible();
    await expect(async () => {
      const close = await chart.getAttribute("data-last-close");
      const ltp = await page.getByTestId("ltp-value").getAttribute("data-value");
      expect(Number(close)).toBeCloseTo(Number(ltp), 2);
    }).toPass({ timeout: 3000 });
  }
  await page
    .getByRole("group", { name: "Interval" })
    .getByRole("button", { name: "5m", exact: true })
    .click();

  await page
    .getByRole("group", { name: "Sections" })
    .getByRole("button", { name: /Orders/ })
    .click();
  const open = page.getByRole("table", { name: "Open orders" });
  await expect(open.getByRole("row").filter({ hasText: "RELIANCE" })).toContainText("rel_trail.py");
  await expect(page.getByRole("table", { name: "Executed orders" })).toContainText("RELIANCE");
  await expect(page.getByRole("table", { name: "Executed orders" })).not.toContainText("HDFCBANK");
});

test("B and S open the order window for this instrument; g s still goes to Strategies", async ({
  page,
}) => {
  await signIn(page);
  await page.goto(RELIANCE);
  await expect(page.getByTestId("candle-chart")).toBeVisible();

  await page.keyboard.press("b");
  const buy = page.getByRole("dialog", { name: /Buy RELIANCE/ });
  await expect(buy).toBeVisible();
  await page.waitForTimeout(400);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: "test-results/screens/symbol-order-1440.png" });
  await page.keyboard.press("Escape");
  await expect(buy).toHaveCount(0);

  await page.keyboard.press("s");
  await expect(page.getByRole("dialog", { name: /Sell RELIANCE/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.keyboard.press("g");
  await page.keyboard.press("s");
  await expect(page).toHaveURL(/\/strategies$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("an instrument's name anywhere opens its page; ⌘K too", async ({ page }) => {
  await signIn(page);
  await page.goto("/positions");
  await page
    .getByRole("table", { name: "Positions" })
    .getByRole("link", { name: /NIFTY OCT FUT/ })
    .click();
  await expect(page).toHaveURL(/\/symbols\/NFO\/NIFTY27OCT26FUT$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("NIFTY OCT FUT");
  await expect(page.getByText(/NFO · Lot 75 · Tick 0\.05 · Expires/)).toBeVisible();
  await expect(page.getByTestId("ltp")).toContainText("₹");

  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("HDFC");
  const palette = page.getByRole("dialog", { name: "Search" });
  await expect(palette.getByRole("option", { name: /HDFCBANK/ }).first()).toBeVisible();
  await palette.getByRole("option", { name: /Open HDFCBANK/ }).click();
  await expect(page).toHaveURL(/\/symbols\/NSE\/HDFCBANK$/);
});

test("a stock's page opens its option chain; a contract's has no link", async ({ page }) => {
  await signIn(page);
  await page.goto(RELIANCE);
  await page.getByRole("link", { name: "Option chain" }).click();
  await expect(page).toHaveURL(/\/options\/NSE\/RELIANCE$/);
  await expect(page.getByRole("button", { name: /Underlying: RELIANCE/ })).toBeVisible();
  await page.goto("/symbols/NFO/NIFTY29SEP2624800PE");
  await expect(page.getByRole("button", { name: "Place paper order" })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Option chain" })).toHaveCount(0);
});

test("an instrument that isn't listed says how to find it", async ({ page }) => {
  await signIn(page);
  await page.goto("/symbols/NSE/NOPE");
  await expect(page.getByRole("heading", { name: "No NOPE on NSE" })).toBeVisible();
});

for (const width of [1280, 1440, 1920]) {
  test(`symbol at ${width}px: no sideways scroll, screens in both themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await page.goto(RELIANCE);
    await expect(page.getByTestId("candle-chart")).toHaveAttribute("data-marks", /^[1-9]/);
    await expect(page.getByRole("table", { name: "Market depth" })).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(500);
      expect(await noOverflow(page)).toEqual([]);
      await page.screenshot({ path: `test-results/screens/symbol-${width}-${theme}.png` });
    }
  });
}
