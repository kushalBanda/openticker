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
  const positions = page.getByRole("link", { name: "Positions" });

  await expect(positions).toHaveAttribute("title", "Positions");
  expect((await page.locator(".sidebar").boundingBox())?.width).toBe(64);
});

test("g then p goes to Positions", async ({ page }) => {
  await page.goto(nextLink());
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  await page.keyboard.press("g");
  await page.keyboard.press("p");

  await expect(page).toHaveURL("/positions");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Positions/);
  await expect(page).toHaveTitle("Positions · OpenTicker");
});
