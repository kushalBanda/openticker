import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Watchlists (ADR 36) over e2e_server.py's lists: Core (NIFTY 50, HDFCBANK,
// TCS, NIFTY OCT FUT, NIFTY SEP 24800 CE) and Banks. Claude adds RELIANCE.

const home = "test-results/e2e-home";

function agent(what: "watch") {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, what],
    { cwd: "..", stdio: "inherit" },
  );
}

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();
}

const table = (page: Page, name = "Core") => page.getByRole("table", { name });
const row = (page: Page, text: string) => table(page).getByRole("row").filter({ hasText: text });
const tab = (page: Page, name: RegExp) =>
  page.getByRole("group", { name: "Watchlists" }).getByRole("button", { name });
const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });

const noOverflow = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .toolbar, .statusbar")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

test("proof: an agent adds RELIANCE to a list and it appears on the page", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await expect(table(page).getByRole("row")).toHaveCount(6); // head + 5
  await expect(row(page, "RELIANCE")).toHaveCount(0);

  const asked = Date.now();
  agent("watch"); // Claude Code, through the MCP tools, in its own process
  const added = row(page, "RELIANCE");
  await expect(added).toBeVisible({ timeout: 5000 });
  console.log(`RELIANCE shown ${Date.now() - asked} ms after the agent was asked`);
  await expect(tab(page, /Core/)).toContainText("6");
  await expect(added.getByTestId("ltp")).toHaveText(/^[\d,]+\.\d\d$/);

  // Who did it, in the Activity log.
  await page.getByRole("link", { name: "Activity" }).first().click();
  await expect(
    page.getByRole("table", { name: "Activity" }).getByRole("row").filter({
      hasText: "RELIANCE added to Core",
    }),
  ).toContainText("Claude");
});

test("each row is live: last price, change, bid, ask, the day's range, volume", async ({
  page,
}) => {
  await signIn(page);
  const hdfc = row(page, "HDFCBANK");
  await expect(hdfc.getByTestId("ltp")).toHaveText(/^1,6\d\d\.\d\d$/);
  await expect(hdfc).toContainText(/[+-][\d,]+\.\d\d \([+-][\d.]+%\)/);
  const cells = hdfc.getByRole("cell");
  for (const n of [3, 4, 5, 6, 7]) await expect(cells.nth(n)).not.toHaveText("—");
  // An index has no book and no volume: missing, never 0.
  const nifty = row(page, "NIFTY 50").getByRole("cell");
  await expect(nifty.nth(3)).toHaveText("—");
  await expect(nifty.nth(7)).toHaveText("—");
  // The price moves with the feed.
  const first = await hdfc.getByTestId("ltp").textContent();
  await expect(hdfc.getByTestId("ltp")).not.toHaveText(first ?? "", { timeout: 5000 });
});

test("B / S from a row, by pointer and by keyboard; a row opens its page", async ({ page }) => {
  await signIn(page);
  const hdfc = row(page, "HDFCBANK");
  await hdfc.hover();
  await hdfc.getByRole("button", { name: "Buy HDFCBANK" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Buy HDFCBANK");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  await page.getByRole("heading", { level: 1 }).click(); // focus off the pill
  // No B / S on an index.
  await expect(row(page, "NIFTY 50").getByRole("button", { name: /Buy/ })).toHaveCount(0);

  await page.keyboard.press("ArrowDown"); // NIFTY 50
  await page.keyboard.press("ArrowDown"); // HDFCBANK
  await expect(hdfc).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("s");
  await expect(page.getByRole("dialog")).toContainText("Sell HDFCBANK");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/symbols\/NSE\/HDFCBANK$/);
  await page.goBack();
  await row(page, "TCS").getByRole("cell").nth(4).click();
  await expect(page).toHaveURL(/\/symbols\/NSE\/TCS$/);
});

test("only the row under the pointer shows its pill", async ({ page }) => {
  await signIn(page);
  const shown = () =>
    page.evaluate(
      () =>
        [...document.querySelectorAll(".row-actions")].filter(
          (el) => getComputedStyle(el).opacity !== "0",
        ).length,
    );
  const hdfc = row(page, "HDFCBANK");
  await hdfc.hover();
  await hdfc.getByRole("button", { name: "Buy HDFCBANK" }).click();
  await page.keyboard.press("Escape"); // focus doesn't come back into the pill
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("ArrowDown"); // a selected row keeps no pill either
  await row(page, "TCS").hover();
  await page.waitForTimeout(250);
  expect(await shown()).toBe(1);
  await page.mouse.move(5, 500); // off the table
  await page.waitForTimeout(250);
  expect(await shown()).toBe(0);
});

test("an instrument's page has a way back to where it was opened from", async ({ page }) => {
  await signIn(page);
  await row(page, "TCS").getByRole("cell").nth(6).click(); // anywhere on the row
  await expect(page).toHaveURL(/\/symbols\/NSE\/TCS$/);
  await page.getByRole("link", { name: "Watchlist" }).first().waitFor();
  await page.locator(".back-link").click();
  await expect(page).toHaveURL(/\/watchlist$/);

  await page.goto("/positions");
  await page
    .getByRole("table", { name: "Positions" })
    .getByRole("row")
    .filter({ hasText: "HDFCBANK" })
    .getByRole("cell")
    .nth(3)
    .click();
  await expect(page).toHaveURL(/\/symbols\/NSE\/HDFCBANK$/);
  await expect(page.locator(".back-link")).toHaveText("Positions");
  await page.locator(".back-link").click();
  await expect(page).toHaveURL(/\/positions$/);

  await page.goto("/symbols/NSE/TCS"); // opened directly
  await expect(page.locator(".back-link")).toHaveText("Watchlist");
});

test("make a list, add and remove, rename, and delete it", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "New list" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("core");
  await page.getByRole("button", { name: "Make list" }).click();
  await expect(page.getByRole("alert")).toContainText("already exists");
  await page.getByRole("textbox", { name: "Name" }).fill("Ideas");
  await page.getByRole("button", { name: "Make list" }).click();
  await expect(toast(page, "Watchlist Ideas made")).toBeVisible();
  await expect(page.getByText("Nothing on Ideas yet.")).toBeVisible();

  await page.getByRole("button", { name: "Add instrument" }).click();
  const add = page.getByRole("dialog", { name: "Add to Ideas" });
  await add.getByRole("combobox").fill("TCS");
  await expect(add.getByRole("option", { name: /TCS/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(toast(page, "TCS added to Ideas")).toBeVisible();
  await expect(add.getByRole("option", { name: /TCS/ })).toContainText("On Ideas");
  await add.getByRole("button", { name: "Done" }).click();
  const tcs = table(page, "Ideas").getByRole("row").filter({ hasText: "TCS" });
  await expect(tcs).toBeVisible();

  await tcs.hover();
  await tcs.getByRole("button", { name: "Remove TCS from Ideas" }).click();
  await expect(tcs).toHaveCount(0);

  await page.getByRole("button", { name: "Rename or delete Ideas" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("Ideas later");
  await page.getByRole("button", { name: "Rename", exact: true }).click();
  await expect(tab(page, /Ideas later/)).toBeVisible();

  await page.getByRole("button", { name: "Rename or delete Ideas later" }).click();
  const hold = page.getByRole("button", { name: "Hold to delete list (press and hold)" });
  await hold.hover();
  await page.mouse.down();
  await page.waitForTimeout(1400);
  await page.mouse.up();
  await expect(toast(page, "Watchlist Ideas later deleted")).toBeVisible();
  await expect(table(page)).toBeVisible(); // back on Core
});

test("the Symbol page's Watch puts it on the list and takes it off", async ({ page }) => {
  await signIn(page);
  await page.goto("/symbols/NFO/NIFTY29SEP2624800PE");
  const watch = page.getByRole("button", { name: "Watch" });
  await watch.click();
  const on = page.getByRole("button", { name: "On Core" });
  await expect(on).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("link", { name: "Watchlist" }).first().click();
  await expect(row(page, "NIFTY SEP 24800 PE")).toBeVisible();

  await page.goBack();
  await page.getByRole("button", { name: "On Core" }).click();
  await expect(page.getByRole("button", { name: "Watch" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

for (const width of [1280, 1440, 1920]) {
  test(`watchlist at ${width}px: no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await expect(row(page, "HDFCBANK").getByTestId("ltp")).not.toHaveText("—");
    await row(page, "HDFCBANK").hover(); // the pill shows
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      expect(await noOverflow(page)).toEqual([]);
      await page.screenshot({ path: `test-results/screens/watchlist-${width}-${theme}.png` });
    }
  });
}

test("no lists yet: one button and a request for your agent", async ({ page }) => {
  await page.route("**/api/v1/watchlists", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { watchlists: [] } })
      : route.continue(),
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await expect(page.getByRole("heading", { name: "No watchlists yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New list" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy the request for your agent" })).toBeVisible();
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/watchlist-empty-1440-${theme}.png` });
  }
});
