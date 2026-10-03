import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The Positions page over the account e2e_server.py seeds: the Positions
// mock's five positions, two strategies holding part of them. Closing tests
// run last: they change the account.

async function openPositions(page: Page) {
  await page.goto(nextLink());
  await page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Positions" })
    .click();
  await expect(page.getByRole("table", { name: "Positions" })).toBeVisible({ timeout: 5000 });
}

const row = (page: Page, name: string) => page.getByRole("row").filter({ hasText: name });

test("each position says who holds it", async ({ page }) => {
  await openPositions(page);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Positions (5)");
  await expect(row(page, "NIFTY SEP 24800 CE")).toContainText("NIFTY short straddle");
  await expect(row(page, "NIFTY OCT FUT")).toContainText("NIFTY futures trend");
  await expect(row(page, "NIFTY OCT FUT")).toContainText("+ you 75");
  await expect(row(page, "RELIANCE")).toContainText("You");
  await expect(row(page, "HDFCBANK")).toContainText("Claude");
  await expect(page.getByTestId("open-pnl")).toContainText("marked live");
});

test("open P&L moves with the ticks", async ({ page }) => {
  await openPositions(page);
  const pnl = page.getByTestId("open-pnl").locator(".value");
  const first = await pnl.textContent();

  await expect(pnl).not.toHaveText(first ?? "", { timeout: 3000 });
});

for (const width of [1280, 1440, 1920]) {
  test(`positions at ${width}px: no sideways scroll, screens in both themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openPositions(page);
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() =>
        [document.documentElement, ...document.querySelectorAll(".tile, .stat, .statusbar")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.className || el.tagName),
      );
      expect(overflow).toEqual([]);
      await page.screenshot({ path: `test-results/screens/positions-${width}-${theme}.png` });
    }
  });
}

test("a shared position offers the strategy's part, all of it, or stopping the strategy", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openPositions(page);
  await row(page, "NIFTY OCT FUT").hover();
  await page.waitForTimeout(200);
  await page.screenshot({ path: "test-results/screens/positions-hover-1440.png" });
  await row(page, "NIFTY OCT FUT").getByRole("button", { name: "Close" }).click();
  const dialog = page.getByRole("dialog", { name: "Close NIFTY OCT FUT" });

  await expect(dialog).toContainText(
    "Long 150: 75 held by NIFTY futures trend (running), 75 placed by you.",
  );
  await expect(dialog.getByRole("radio")).toHaveCount(3);
  await expect(dialog.getByRole("radio", { name: /Close the strategy's 75/ })).toBeChecked();
  await expect(dialog.getByRole("button", { name: "Sell 75 at market" })).toBeEnabled();
  await expect(dialog).toContainText("Charges (est.)");
  await expect(dialog.getByText(/^₹/)).toBeVisible();
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/positions-close-1440-${theme}.png` });
  }

  await dialog.getByRole("radio", { name: /Close all 150/ }).check();
  await expect(dialog.getByRole("button", { name: "Sell 150 at market" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("guardrail: close a position in two actions, under five seconds", async ({ page }) => {
  await openPositions(page);
  const started = Date.now();

  await row(page, "RELIANCE").hover();
  await row(page, "RELIANCE").getByRole("button", { name: "Close" }).click(); // 1
  await page.getByRole("dialog").getByRole("button", { name: "Sell 10 at market" }).click(); // 2

  await expect(page.getByTestId("notice")).toContainText("Closed RELIANCE: sold 10");
  await expect(row(page, "RELIANCE")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Positions (4)");
  expect(Date.now() - started).toBeLessThan(5000);
});

test("closing a strategy's part sends its runner the command", async ({ page }) => {
  await openPositions(page);
  await row(page, "NIFTY OCT FUT").hover();
  await row(page, "NIFTY OCT FUT").getByRole("button", { name: "Close" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sell 75 at market" }).click();

  await expect(page.getByTestId("notice")).toContainText(
    "NIFTY futures trend is closing its 75 NIFTY OCT FUT.",
  );
});
