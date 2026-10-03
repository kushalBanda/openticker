import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The README's screenshots (docs/images/), in light, from the e2e server's
// example account. Only when asked, since they are committed:
//   README_SCREENS=1 pnpm e2e --project=app readme

test.skip(!process.env.README_SCREENS, "README_SCREENS=1 takes the README's screenshots");

const shoot = (page: Page, name: string) =>
  page.screenshot({ path: `../docs/images/web-${name}.png` });

async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 5_000 });
  await page.waitForTimeout(1_500); // charts drawn, rolling digits settled
}

test("README screenshots", async ({ page }) => {
  test.setTimeout(120_000);
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());

  await open(page, "/");
  await shoot(page, "dashboard");
  await open(page, "/positions");
  await shoot(page, "positions");
  await open(page, "/options");
  await shoot(page, "option-chain");
  await open(page, "/strategies");
  await page.getByRole("link", { name: "NIFTY short straddle" }).click();
  await open(page, page.url());
  await shoot(page, "strategy");
  await open(page, "/symbols/NSE/RELIANCE");
  await shoot(page, "symbol");
});
