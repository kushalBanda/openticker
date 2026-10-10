import { execFileSync } from "node:child_process";
import { expect, type Locator, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Settings (ADR 33, ADR 37). Runs last (playwright.config.ts): it logs the
// broker out and in, and wipes the paper account.

const home = "test-results/e2e-home";

function agent(what: "end-runs") {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, what],
    { cwd: "..", stdio: "inherit" },
  );
}

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
}

async function hold(page: Page, button: Locator) {
  // Held where the button is once the page has stopped moving: a section
  // above that loads late would slide it out from under the pointer.
  await page.waitForLoadState("networkidle");
  await button.scrollIntoViewIfNeeded();
  await button.hover();
  await page.mouse.down();
  await page.waitForTimeout(1400);
  await page.mouse.up();
}

const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });
const broker = (page: Page) => page.locator("#broker");

for (const width of [1280, 1440, 1920]) {
  test(`settings at ${width}px: every section, no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await expect(broker(page).getByText("Connected")).toBeVisible();
    await expect(page.locator("#account")).toContainText("₹25,00,000.00");
    await expect(page.locator("#instruments")).toContainText("NSE");
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() =>
        [document.documentElement, ...document.querySelectorAll(".tile, .statusbar")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.className || el.tagName),
      );
      expect(overflow).toEqual([]);
      await page.screenshot({ path: `test-results/screens/settings-${width}-${theme}.png` });
      if (width === 1440) {
        await page.screenshot({
          path: `test-results/screens/settings-full-1440-${theme}.png`,
          fullPage: true,
        });
      }
    }
  });
}

test("proof: disconnect, then connect through the broker's login and its redirect", async ({
  page,
}) => {
  await signIn(page);
  await broker(page).getByRole("button", { name: "Disconnect" }).click();
  await expect(toast(page, "Fake disconnected")).toBeVisible();
  await expect(broker(page).getByText("Not connected")).toBeVisible();
  await expect(
    page.locator("#instruments").getByRole("button", { name: "Connect to sync" }),
  ).toBeDisabled();

  await broker(page).getByRole("button", { name: "Log in to Fake" }).click();
  await expect(page).toHaveURL(/localhost:8752\/connect\/login/); // the broker's own site
  await page.getByRole("link", { name: "Log in" }).click();

  await expect(page).toHaveURL(/127\.0\.0\.1:8751\/settings$/); // flag read and cleared
  await expect(toast(page, "Fake connected")).toBeVisible();
  await expect(broker(page).getByText("Connected", { exact: true })).toBeVisible();
  await expect(broker(page)).toContainText("Last login");
  await page.getByRole("link", { name: "Activity" }).first().click();
  await expect(
    page
      .getByRole("table", { name: "Activity" })
      .getByRole("row")
      .filter({ hasText: "Fake connected" }),
  ).toContainText("You");
});

test("a new key is shown once, then revoked with the hold", async ({ page }) => {
  await signIn(page);
  const keys = page.locator("#keys");
  await keys.getByRole("button", { name: "Create key" }).click();
  await keys.getByRole("textbox", { name: "Key name" }).fill("laptop");
  await keys.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByTestId("new-key")).toContainText("shown this once");
  await expect(page.getByTestId("new-key")).toContainText("otk_");
  const row = keys.getByRole("row").filter({ hasText: "laptop" });
  await expect(row).toContainText("Full");

  await hold(page, row.getByRole("button", { name: "Hold to revoke (press and hold)" }));
  await expect(toast(page, "Key laptop revoked")).toBeVisible();
  await expect(row).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("new-key")).toHaveCount(0); // never shown again
});

test("proof: reset refused while a strategy runs, then succeeds", async ({ page }) => {
  await signIn(page);
  const zone = page.getByTestId("reset-zone");
  const button = zone.getByRole("button", { name: "Hold to reset (press and hold)" });
  await expect(button).toBeDisabled();
  await zone.getByRole("textbox", { name: "Type RESET to confirm" }).fill("RESET");
  await expect(button).toBeEnabled();

  await hold(page, button);
  const refusal = zone.getByRole("alert");
  await expect(refusal).toContainText("Stop strategy NIFTY short straddle");
  await expect(refusal).toContainText("first");
  await page.setViewportSize({ width: 1440, height: 900 });
  await zone.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/screens/settings-reset-refused-1440.png" });

  agent("end-runs");
  await hold(page, button);

  await expect(toast(page, "Paper account reset to ₹25,00,000.00")).toBeVisible();
  await expect(refusal).toHaveCount(0);
  await page.getByRole("link", { name: "Positions" }).first().click();
  await expect(page.getByRole("table", { name: "Positions" })).toHaveCount(0);

  // The brain is kept: today's debriefed page keeps its trades and figures.
  const days = await (await page.request.get("/api/v1/brain/notes?kind=day&limit=1")).json();
  await page.goto(`/brain/days/${days.notes[0].key}`);
  await expect(page.getByText(/Kept from before the paper account was reset/)).toBeVisible();
  await expect(page.getByTestId("day-fills")).not.toContainText(/^Fills0$/);
  const trades = page.getByRole("table", { name: "Trades and trade-offs" });
  await expect(trades.getByRole("row").filter({ hasText: "NIFTY short straddle" })).toContainText(
    "Scheduled entry",
  );
});

test("theme: Settings and the status bar agree", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await signIn(page);
  const html = page.locator("html");
  const theme = page.getByRole("group", { name: "Theme" });

  await expect(page.getByRole("link", { name: "TradingView Lightweight Charts™" })).toHaveAttribute(
    "href",
    "https://www.tradingview.com/",
  );
  await theme.getByRole("button", { name: "Light" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(theme.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
  await theme.getByRole("button", { name: "System" }).click();
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "System" }),
  ).toHaveAttribute("aria-pressed", "true");
});
