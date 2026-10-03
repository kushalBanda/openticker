import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Events from outside the server (e2e_agent.py): Claude Code placing an order
// through MCP in its own process, and the daemon killing a strategy. Both
// reach the page only through the audit log the stream tails. Runs after the
// other specs (playwright.config.ts): Claude's TCS stays open.

const home = "test-results/e2e-home";

function agent(what: "order" | "kill") {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, what],
    {
      cwd: "..",
      stdio: "inherit",
    },
  );
}

async function signIn(page: Page, path: string) {
  await page.goto(nextLink());
  await page.goto(path);
  await expect(page.getByTestId("price-source")).toContainText("live", { timeout: 5000 });
}

const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });

test("an order Claude places over MCP toasts as Claude within a second", async ({ page }) => {
  await signIn(page, "/positions");

  agent("order");

  const filled = toast(page, "Buy 5 TCS at");
  await expect(filled).toBeVisible({ timeout: 1000 });
  await expect(filled).toContainText("Fill");
  await expect(filled).toContainText("Claude");
  await expect(page.getByRole("table", { name: "Positions" })).toContainText("TCS");
});

test("a kill raises a banner, a toast, the bell and the tab's dot; Activity has it live", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, "/activity");
  const table = page.getByRole("table", { name: "Activity" });
  await expect(table.getByRole("row").filter({ hasText: "Buy 5 TCS at" })).toContainText("Claude");
  await expect(page.getByTestId("bell-count")).toHaveCount(0);

  agent("kill");

  const banner = page.getByTestId("kill-banner");
  await expect(banner).toContainText(
    "SBIN mean reversion stopped: daily loss limit ₹2,000 reached",
  );
  await expect(toast(page, "SBIN mean reversion stopped")).toHaveAttribute("data-urgent", "true");
  await expect(page.getByTestId("bell-count")).toHaveText("1");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("data-dot", "true");
  const stopped = table.getByRole("row").filter({ hasText: "SBIN mean reversion stopped" });
  await expect(stopped).toContainText("SBIN mean reversion"); // by the strategy, by name

  await page.getByRole("group", { name: "Who" }).getByRole("button", { name: "Claude" }).click();
  await expect(table.getByRole("row").filter({ hasText: "SBIN" })).toHaveCount(0);
  await expect(table.getByRole("row").filter({ hasText: "Buy 5 TCS at" })).toHaveCount(1);
  await page
    .getByRole("group", { name: "Kind" })
    .getByRole("button", { name: "Strategies" })
    .click();
  await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
  await page.getByRole("group", { name: "Who" }).getByRole("button", { name: "Anyone" }).click();
  await expect(stopped).toHaveCount(1);

  await page.getByRole("button", { name: "Events, 1 unread" }).click();
  const bell = page.getByRole("dialog", { name: "Events" });
  await expect(bell.getByRole("listitem").first()).toContainText("SBIN mean reversion stopped");
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/activity-1440-${theme}.png` });
  }
  await bell.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByTestId("bell-count")).toHaveCount(0);
  await expect(banner).toHaveCount(0);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("data-dot", "false");
});

for (const width of [1280, 1920]) {
  test(`activity at ${width}px: no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page, "/activity");
    await page
      .getByRole("group", { name: "Period" })
      .getByRole("button", { name: "7 days" })
      .click();
    await expect(page.getByRole("table", { name: "Activity" })).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() =>
        [document.documentElement, ...document.querySelectorAll(".tile, .statusbar, .banners")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.className || el.tagName),
      );
      expect(overflow).toEqual([]);
      await page.screenshot({ path: `test-results/screens/activity-${width}-${theme}.png` });
    }
  });
}
