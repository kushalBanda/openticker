import { expect, test } from "@playwright/test";
import { nextLink } from "./links";

test("the printed link signs in and NIFTY 50 ticks in the status bar", async ({ page }) => {
  await page.goto(nextLink());

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("navigation", { name: "Pages" })).toBeVisible();
  const nifty = page.getByTestId("index-NIFTY 50");
  const value = /^NIFTY 50 24,\d{3}\.\d{2} [+-]\d+\.\d{2} \([+-]\d+\.\d{2}%\)$/;
  await expect(nifty).toHaveAttribute("aria-label", value, { timeout: 1000 });
  await expect(page.getByTestId("price-source")).toHaveText("Fake · live", { timeout: 3000 });

  const first = await nifty.getAttribute("aria-label");
  await expect(nifty).not.toHaveAttribute("aria-label", first ?? "", { timeout: 2000 });
});

test("a used link shows the expired page", async ({ page, browser }) => {
  const link = nextLink();
  await page.goto(link);
  const other = await browser.newPage();

  const response = await other.goto(link);

  expect(response?.status()).toBe(400);
  await expect(other.getByRole("heading")).toHaveText("This sign-in link has expired");
  await expect(other.getByText("openticker-serve ui login")).toBeVisible();
});

test("without a session the app says how to sign in", async ({ page }) => {
  await page.goto("/positions");

  await expect(page.getByRole("heading")).toHaveText("Sign in with a link from your terminal");
  await expect(page.getByText("openticker-serve ui login")).toBeVisible();
});

test("signing out returns to the sign-in page", async ({ page }) => {
  await page.goto(nextLink());
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();

  await expect(page.getByRole("heading")).toHaveText("Sign in with a link from your terminal");
  await page.reload();
  await expect(page.getByRole("heading")).toHaveText("Sign in with a link from your terminal");
});
