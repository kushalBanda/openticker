import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The Dashboard (ADR 34). Runs after the events specs (playwright.config.ts):
// it has Claude place an order and a strategy be killed while the browser is
// away, then comes back.

const home = "test-results/e2e-home";

function agent(what: "order" | "kill" | "later") {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, what],
    { cwd: "..", stdio: "inherit" },
  );
}

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/");
  await expect(page.getByTestId("today-hero")).toBeVisible();
}

const noOverflow = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .today-hero, .statusbar")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

test("proof: back after a while, the Dashboard says what happened meanwhile", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await expect(page.getByTestId("since")).toHaveCount(0); // the day's first visit

  agent("later"); // 15 minutes pass
  agent("order"); // then Claude bought 5 TCS
  agent("kill"); // and SBIN mean reversion hit its daily loss limit
  await page.reload();

  const since = page.getByTestId("since");
  await expect(since).toContainText("Since you were here at");
  await expect(since.getByRole("link", { name: "1 fill" })).toHaveAttribute("href", "/trades");
  await expect(since.getByRole("link", { name: "SBIN mean reversion stopped" })).toBeVisible();
  await expect(since).toContainText("you're");
  await expect(page.getByTestId("today-net")).toContainText("₹");
  await expect(page.getByTestId("intraday-chart")).toBeVisible();
  await expect(page.locator("#tv-attr-logo")).toHaveCount(0); // credited in Settings instead
  await expect(page).toHaveTitle("Dashboard · OpenTicker");

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `test-results/screens/dashboard-1440-${theme}.png` });
    await page.screenshot({
      path: `test-results/screens/dashboard-full-1440-${theme}.png`,
      fullPage: true,
    });
  }

  await page.getByRole("link", { name: "Positions" }).first().click();
  await expect(page).toHaveTitle("Positions · OpenTicker");
});

for (const width of [1280, 1920]) {
  test(`dashboard at ${width}px: every tile, no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await expect(page.getByRole("table", { name: "Open positions" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Daily P&L" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent events" })).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      expect(await noOverflow(page)).toEqual([]);
      await page.screenshot({ path: `test-results/screens/dashboard-${width}-${theme}.png` });
    }
  });
}

test("first run: the hero and the four steps until the first fill", async ({ page }) => {
  await page.route("**/api/v1/setup?*", (route) =>
    route.fulfill({
      json: {
        broker: "fake",
        broker_connected: true,
        instruments_synced_today: true,
        instrument_count: 9,
        agent_seen: null,
        first_fill_at: null,
        done: false,
      },
    }),
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Your agent trades. You watch." })).toBeVisible();
  const steps = page.locator(".step");
  await expect(steps.nth(0)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(2)).toHaveAttribute("data-state", "now");
  await expect(steps.nth(2)).toContainText("claude mcp add openticker");
  expect(await noOverflow(page)).toEqual([]);
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: `test-results/screens/dashboard-first-run-1440-${theme}.png`,
      fullPage: true,
    });
  }
});
