import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Strategies over e2e_server.py's five (e2e_strategies.py): a running NIFTY
// straddle and a running NIFTY futures trend on alerts, RELIANCE breakout
// listening for alerts, a scheduled BANKNIFTY iron condor, and SBIN mean
// reversion killed; each with a summer of runs after costs, and reviews.
// The kill runs last: it locks the straddle.

async function openStrategies(page: Page) {
  await page.goto(nextLink());
  await page.getByRole("link", { name: "Strategies" }).click();
  await expect(page.getByRole("table", { name: "Strategies" })).toBeVisible({ timeout: 5000 });
}

async function openStrategy(page: Page, name: string) {
  await openStrategies(page);
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
}

const row = (page: Page, name: string) =>
  page.getByRole("table", { name: "Strategies" }).getByRole("row").filter({ hasText: name });

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .stat, .statusbar")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );
  expect(overflow).toEqual([]);
}

async function screens(page: Page, name: string) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await noOverflow(page);
    await page.screenshot({ path: `test-results/screens/${name}-${theme}.png`, fullPage: true });
  }
}

test("each strategy says what it is doing, what it made and its last verdict", async ({ page }) => {
  await openStrategies(page);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Strategies (5)");
  await expect(row(page, "NIFTY short straddle")).toContainText("Running");
  await expect(row(page, "NIFTY short straddle")).toContainText("exit 15:15");
  await expect(row(page, "NIFTY short straddle")).toContainText("Keep");
  await expect(row(page, "NIFTY futures trend")).toContainText("Change");
  await expect(row(page, "RELIANCE breakout")).toContainText("Listening");
  await expect(row(page, "RELIANCE breakout")).toContainText("never");
  await expect(row(page, "BANKNIFTY iron condor")).toContainText("Scheduled");
  await expect(row(page, "BANKNIFTY iron condor")).toContainText("Mon 09:20");
  await expect(row(page, "BANKNIFTY iron condor")).toContainText("Retire");
  await expect(row(page, "SBIN mean reversion")).toContainText("Killed");

  await page.getByRole("button", { name: "Signal", pressed: false }).click();
  await expect(page.getByRole("table", { name: "Strategies" }).getByRole("row")).toHaveCount(4);
  await page.getByRole("button", { name: "Killed", pressed: false }).click();
  await expect(page.getByRole("table", { name: "Strategies" }).getByRole("row")).toHaveCount(2);

  await row(page, "SBIN mean reversion").getByRole("cell").nth(4).click(); // Runs, not the name
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("SBIN mean reversion");
});

test("a row's own button acts without opening the strategy", async ({ page }) => {
  await openStrategies(page);
  await row(page, "NIFTY short straddle").hover();
  await row(page, "NIFTY short straddle").getByRole("button", { name: "Stop" }).click();

  await expect(page.getByRole("dialog", { name: "Stop NIFTY short straddle?" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Strategies (5)");
  await page.keyboard.press("Escape");
});

test("today's P&L moves with the open legs' ticks", async ({ page }) => {
  await openStrategies(page);
  const today = page.getByTestId("strategies-today").locator(".value");
  await expect(today).not.toHaveText("—");
  const first = await today.textContent();

  await expect(today).not.toHaveText(first ?? "", { timeout: 3000 });
});

for (const width of [1280, 1440, 1920]) {
  test(`strategies at ${width}px: no sideways scroll, screens in both themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStrategies(page);
    await row(page, "BANKNIFTY iron condor").hover();
    await screens(page, `strategies-${width}`);
    await page.getByRole("link", { name: "NIFTY short straddle", exact: true }).click();
    await expect(page.getByTestId("equity-chart")).toBeVisible();
    await screens(page, `strategy-${width}`);
  });
}

test("a signal strategy's frame: alerts, its definition and the alert URL", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openStrategy(page, "NIFTY futures trend");

  await expect(page.getByRole("table", { name: "Recent alerts" }).getByRole("row")).toHaveCount(3);
  const definition = page.getByTestId("definition");
  await expect(definition).toContainText("NIFTY27OCT26FUT · 75 · long only");
  await expect(definition).toContainText("0.6% / 1.5%");
  await expect(definition).toContainText("Alert URL");
  await expect(page.getByTestId("latest-review")).toContainText("exit by 15:00");
  await screens(page, "strategy-signal-1440");

  await page.getByRole("button", { name: /Signals/ }).click();
  await expect(page.getByRole("table", { name: "Alerts" })).toContainText("long only");
  await page.getByRole("button", { name: /Runs/ }).click();
  await expect(page.getByRole("table", { name: "Runs" }).getByRole("row")).not.toHaveCount(0);
  await page.getByRole("button", { name: "Ledger" }).click();
  await expect(page.getByText("Net after costs")).toBeVisible();
  await page.getByRole("button", { name: /Reviews/ }).click();
  await expect(page.getByRole("list")).toContainText("Change");

  await page.getByRole("main").getByRole("link", { name: "Strategies", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Strategies (5)");
});

test("rotating an alert URL shows the new one once", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openStrategy(page, "RELIANCE breakout");

  await page.getByRole("button", { name: "Rotate URL" }).click();
  const dialog = page.getByRole("dialog", { name: "Rotate the alert URL?" });
  await dialog.getByRole("button", { name: "Rotate URL" }).click();
  await expect(page.getByRole("dialog", { name: "New alert URL" })).toContainText(
    "/webhooks/strategies/otw_",
  );
  await page.getByRole("button", { name: "Copy the alert URL" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "/webhooks/strategies/",
  );
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("definition")).toContainText("••••••••");
});

test("guardrail: kill a running strategy with the hold in two actions, under five seconds", async ({
  page,
}) => {
  await openStrategies(page);
  const started = Date.now();

  await page.getByRole("link", { name: "NIFTY short straddle", exact: true }).click(); // 1
  const hold = page.getByRole("button", { name: "Hold to kill (press and hold)" });
  await hold.hover();
  await page.mouse.down(); // 2: held
  await page.waitForTimeout(1300);
  await page.mouse.up();

  await expect(page.getByRole("button", { name: "Release" })).toBeVisible();
  await expect(page.locator(".page-head")).toContainText("Killed");
  expect(Date.now() - started).toBeLessThan(5000);
  await expect(page.getByTestId("toast")).toContainText("Killed NIFTY short straddle");
});
