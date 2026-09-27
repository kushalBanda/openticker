import { expect, test } from "@playwright/test";
import { nextLink } from "./links";

test("first visit follows the system; the toggle is remembered", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(nextLink());
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");

  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
});
