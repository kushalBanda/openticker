import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Trades over e2e_server.py's fills: today's TCS round trip (bought at the
// ask 3,970.05, sold at the bid 4,138.95) and yesterday's, from before fills
// kept their realized P&L and charge breakdown.

async function openTrades(page: Page) {
  await page.goto(nextLink());
  await page.getByRole("link", { name: "Trades" }).click();
  await expect(page.getByRole("table", { name: "Trades" })).toBeVisible({ timeout: 5000 });
}

const rows = (page: Page, text: string) =>
  page.getByRole("table", { name: "Trades" }).getByRole("row").filter({ hasText: text });

const amount = (text: string) => Number(text.replace(/[₹,]/g, ""));

test("proof: a closing fill shows its realized P&L and itemised charges that sum to the total", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTrades(page);

  const tcs = rows(page, "TCS");
  await expect(tcs).toHaveCount(2);
  const sold = tcs.filter({ hasText: "Sell" });
  await expect(sold).toContainText("4,138.95");
  await expect(sold).toContainText("+2,533.50");
  await expect(tcs.filter({ hasText: "Buy" })).toContainText("0.00");

  const charges = sold.getByRole("button", { name: /Charges on this fill/ });
  await charges.hover();
  const popover = page.getByRole("tooltip");
  await expect(popover).toContainText("Brokerage");
  await expect(popover).toContainText("STT");
  await expect(popover).toContainText("GST");
  const figures = (await popover.locator("dd").allTextContents()).map(amount);
  const total = figures.pop() ?? Number.NaN;
  const sum = figures.reduce((a, b) => a + b, 0);
  expect(Math.abs(sum - total)).toBeLessThan(0.005);
  expect((await charges.textContent()) ?? "").toContain(total.toFixed(2));
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(300);
    await page.screenshot({ path: `test-results/screens/trades-charges-1440-${theme}.png` });
  }
  await page.keyboard.press("Escape");
  await expect(popover).toBeHidden();

  await expect(page.getByTestId("realized")).toContainText("after charges");
});

test("this week shows yesterday's older fills with — and says they aren't counted", async ({
  page,
}) => {
  await openTrades(page);
  await page.getByRole("button", { name: "This week", pressed: false }).click();

  const tcs = rows(page, "TCS");
  await expect(tcs).toHaveCount(4);
  const older = tcs.filter({ hasText: "Mon" });
  await expect(older).toHaveCount(2);
  await expect(older.first().getByTitle("Not recorded for fills this old")).toBeVisible();
  await expect(older.first().getByRole("button", { name: /Charges on this fill/ })).toHaveCount(0);
  await expect(page.getByTestId("realized")).toContainText("2 older fills not counted");
  await page.screenshot({ path: "test-results/screens/trades-week-1280.png" });

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV" }).click();
  expect((await download).suggestedFilename()).toBe("trades-2026-09-21.csv");
});

for (const width of [1280, 1440, 1920]) {
  test(`trades at ${width}px: no sideways scroll, screens in both themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openTrades(page);
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
      await page.screenshot({ path: `test-results/screens/trades-${width}-${theme}.png` });
    }
  });
}
