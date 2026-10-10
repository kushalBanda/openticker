import { expect, test } from "@playwright/test";
import { nextLink } from "./links";

// No sideways scroll at any supported width, in either theme (DESIGN.md), with
// a screenshot of each for the review beside the mock.
for (const width of [1280, 1440, 1920]) {
  test(`shell at ${width}px has no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(nextLink());
    await expect(page.getByTestId("price-source")).toHaveText("Fake · live", { timeout: 3000 });
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400); // let colour transitions settle before the capture
      const overflow = await page.evaluate(() =>
        [document.documentElement, ...document.querySelectorAll(".tile, .statusbar")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.className || el.tagName),
      );
      expect(overflow).toEqual([]);
      await page.screenshot({ path: `test-results/screens/shell-${width}-${theme}.png` });
    }
  });
}

test("below 1440px the sidebar is a rail with tooltips", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(nextLink());
  const portfolio = page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Portfolio" });

  await expect(portfolio).toHaveAttribute("title", "Portfolio");
  expect((await page.locator(".sidebar").boundingBox())?.width).toBe(64);
});

test("Portfolio is one sidebar item; its tabs are Positions, Orders and Trades", async ({
  page,
}) => {
  await page.goto(nextLink());
  const portfolio = page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Portfolio" });
  await portfolio.click();
  await expect(page).toHaveURL("/positions");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Positions/);
  await expect(page).toHaveTitle("Positions · OpenTicker");

  const tabs = page.getByRole("group", { name: "Portfolio" });
  for (const [name, path] of [
    ["Orders", "/orders"],
    ["Trades", "/trades"],
  ] as const) {
    await tabs.getByRole("button", { name }).click();
    await expect(page).toHaveURL(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(new RegExp(`^${name}`));
    await expect(tabs.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
    await expect(portfolio).toHaveAttribute("aria-current", "page");
  }
});
