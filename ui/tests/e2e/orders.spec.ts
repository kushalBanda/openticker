import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Orders and the order window over e2e_server.py's book: a resting HDFCBANK
// limit (you), a script's RELIANCE stop, Codex's refused future, a cancel.

async function openOrders(page: Page) {
  await page.goto(nextLink());
  await page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Portfolio" })
    .click();
  await page
    .getByRole("group", { name: "Portfolio" })
    .getByRole("button", { name: "Orders" })
    .click();
  await expect(page.getByRole("table", { name: "Open orders" })).toBeVisible({ timeout: 5000 });
}

const open = (page: Page) => page.getByRole("table", { name: "Open orders" });
const executed = (page: Page) => page.getByRole("table", { name: "Executed orders" });

test("the book says what each order is and who placed it", async ({ page }) => {
  await openOrders(page);

  const hdfc = open(page).getByRole("row").filter({ hasText: "HDFCBANK" });
  await expect(hdfc).toContainText("0 / 25");
  await expect(hdfc).toContainText("1,640.00");
  await expect(hdfc).toContainText("You");
  const stop = open(page).getByRole("row").filter({ hasText: "trg." });
  await expect(stop).toContainText("Trigger pending");
  await expect(stop).toContainText("rel_trail.py");
  const refused = executed(page).getByRole("row").filter({ hasText: "NIFTY OCT FUT" });
  await expect(refused.first()).toContainText("Rejected");
  await expect(refused.first()).toContainText("Codex");
  await expect(executed(page)).toContainText("Insufficient sandbox funds");
  await expect(
    executed(page).getByRole("row").filter({ hasText: "NIFTY short straddle" }),
  ).toHaveCount(2);

  await page.getByRole("button", { name: "Agents", pressed: false }).click();
  await expect(page.getByText("No open orders from them.")).toBeVisible();
  await expect(executed(page).getByRole("row")).toHaveCount(4); // head, Claude, Codex + reason
});

for (const width of [1280, 1440, 1920]) {
  test(`orders at ${width}px: no sideways scroll, screens in both themes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openOrders(page);
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
      await page.screenshot({ path: `test-results/screens/orders-${width}-${theme}.png` });
    }
  });
}

test("proof: place a limit from ⌘K, modify it, cancel it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openOrders(page);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Search" });
  await page.keyboard.type("RELI");
  await expect(palette.getByRole("option", { name: /RELIANCE/ }).first()).toBeVisible();
  await page.waitForTimeout(400); // the entrance settles
  await page.screenshot({ path: "test-results/screens/palette-1440.png" });
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: /Buy RELIANCE/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Limit", pressed: true })).toBeVisible();
  await dialog.getByLabel("Qty.").fill("10");
  await dialog.getByLabel("Price", { exact: true }).fill("2900");
  await expect(dialog.getByTestId("order-cost")).toContainText("₹");
  await expect(dialog.getByTestId("order-cost")).toContainText("Charges (est.)");
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/order-dialog-1440-${theme}.png` });
  }
  await dialog.locator("button[type=submit]").click();

  await expect(
    page.getByTestId("toast").filter({ hasText: "Buy 10 RELIANCE at 2,900.00 is open." }),
  ).toBeVisible();
  const mine = open(page).getByRole("row").filter({ hasText: "2,900.00" });
  await expect(mine).toContainText("You");

  await mine.hover();
  await mine.getByRole("button", { name: "Modify" }).click();
  const change = page.getByRole("dialog", { name: /Modify buy RELIANCE/ });
  await change.getByLabel("Price", { exact: true }).fill("2905");
  await change.getByRole("button", { name: "Modify" }).click();
  await expect(
    page.getByTestId("toast").filter({ hasText: "Modified: Buy 10 RELIANCE at 2,905.00." }),
  ).toBeVisible();
  const moved = open(page).getByRole("row").filter({ hasText: "2,905.00" });
  await expect(moved).toHaveCount(1);

  await moved.hover();
  await moved.getByRole("button", { name: "Cancel" }).click();
  await expect(
    page.getByTestId("toast").filter({ hasText: "Cancelled buy 10 RELIANCE." }),
  ).toBeVisible();
  await expect(open(page).getByRole("row").filter({ hasText: "2,905.00" })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancelled", pressed: false }).click();
  await expect(executed(page).getByRole("row").filter({ hasText: "RELIANCE" })).toHaveCount(2);
});

test("an order the funds can't cover is refused in the window, with the reason", async ({
  page,
}) => {
  await openOrders(page);
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("NIFTY27OCT");
  await expect(
    page.getByRole("dialog", { name: "Search" }).getByRole("option", { name: /^NIFTY OCT FUT/ }),
  ).toBeVisible();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: /Buy NIFTY OCT FUT/ });
  await dialog.getByRole("button", { name: "Market" }).click();
  await dialog.getByLabel("Qty.").fill("100");
  await expect(dialog.getByText("A multiple of the lot, 75")).toBeVisible();
  await dialog.getByLabel("Qty.").fill("7500");
  await expect(dialog.getByRole("alert")).toContainText("Not enough funds");
  await dialog.locator("button[type=submit]").click();
  await expect(dialog.getByRole("alert").last()).toContainText("insufficient sandbox funds");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll(".dialog, .dialog *")]
      .filter(
        (el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "visible",
      )
      .map((el) => el.className || el.tagName),
  );
  expect(overflow).toEqual([]);
}

for (const width of [390, 1440]) {
  test(`the order window never scrolls sideways at ${width}px, open or closed`, async ({
    page,
  }) => {
    let closed = false;
    await page.routeWebSocket(/\/stream/, (socket) => {
      const server = socket.connectToServer();
      server.onMessage((message) => {
        const data = JSON.parse(String(message));
        if (closed && data.type === "status") data.feed.market_open = false;
        socket.send(JSON.stringify(data));
      });
    });
    await page.setViewportSize({ width, height: 900 });
    await openOrders(page);
    await page.keyboard.press("ControlOrMeta+k");
    await page.keyboard.type("RELI");
    await expect(page.getByRole("option", { name: /RELIANCE/ }).first()).toBeVisible();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: /Buy RELIANCE/ });
    await expect(dialog.getByTestId("order-cost")).toContainText("₹");
    await expect(dialog.getByLabel("Price", { exact: true })).toBeFocused();
    await expect(dialog.getByText("In steps of")).toHaveCount(0);
    await page.waitForTimeout(400);
    await noSidewaysScroll(page);
    await page.screenshot({ path: `test-results/screens/order-dialog-${width}-open.png` });
    await page.keyboard.press("Escape");

    closed = true;
    await page.reload();
    await expect(page.getByRole("table", { name: "Open orders" })).toBeVisible({ timeout: 5000 });
    await page.keyboard.press("ControlOrMeta+k");
    await page.keyboard.type("RELI");
    await expect(page.getByRole("option", { name: /RELIANCE/ }).first()).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(dialog.getByRole("status")).toContainText("The market is closed");
    await expect(dialog.locator("button[type=submit]")).toBeDisabled();
    await expect(dialog.locator("button[type=submit]")).toHaveText("Buy");
    await page.waitForTimeout(400);
    await noSidewaysScroll(page);
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(300);
      await page.screenshot({
        path: `test-results/screens/order-dialog-${width}-closed-${theme}.png`,
      });
    }
  });
}
