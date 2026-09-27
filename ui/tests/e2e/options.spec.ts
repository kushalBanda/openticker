import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The option chain (ADR 38) over e2e_server.py's NIFTY: four expiries,
// strikes 50 apart from 23,800 to 25,800, priced off the walking NIFTY 50.
// Placing the iron fly changes the account, so this runs in its own project
// after the rest of the app's.

async function signIn(page: Page, path = "/options") {
  await page.goto(nextLink());
  await page.evaluate(() => localStorage.clear());
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Option chain", level: 1 })).toBeVisible();
}

const chain = (page: Page) => page.getByRole("table", { name: "Option chain" });
const toast = (page: Page, text: string | RegExp) =>
  page.getByTestId("toast").filter({ hasText: text });

const noOverflow = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .toolbar, .tray, .stats")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

/** Picks the bid (sell) or ask (buy) of one contract from the chain. */
async function pick(page: Page, side: "Sell" | "Buy", name: string) {
  await chain(page)
    .getByRole("button", { name: new RegExp(`^${side} ${name} at [\\d,.]+$`) })
    .click();
}

test("proof: the mock's iron fly shows its payoff and places as 4 paper orders", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await expect(chain(page).locator("tbody tr[data-atm]")).toContainText("24,800");
  await page
    .getByRole("group", { name: "Strikes either side" })
    .getByRole("button", { name: "±20" })
    .click();
  await expect(chain(page).getByRole("cell", { name: "25,400", exact: true })).toBeVisible();

  await pick(page, "Sell", "NIFTY SEP 24800 CE");
  await pick(page, "Sell", "NIFTY SEP 24800 PE");
  await pick(page, "Buy", "NIFTY SEP 25400 CE");
  await pick(page, "Buy", "NIFTY SEP 24200 PE");
  const basket = page.getByTestId("basket");
  await expect(basket.getByTestId("basket-leg")).toHaveCount(4);
  await expect(basket).toContainText("4 legs · NIFTY 29 Sep");

  // The mock's prices, typed over the picked ones.
  for (const [name, at] of [
    ["NIFTY SEP 24800 CE", "128.05"],
    ["NIFTY SEP 24800 PE", "139.20"],
    ["NIFTY SEP 25400 CE", "3.10"],
    ["NIFTY SEP 24200 PE", "6.15"],
  ] as const) {
    await basket.getByRole("spinbutton", { name: `Price of ${name}` }).fill(at);
  }
  await expect(basket.getByTestId("net-premium")).toHaveText("₹19,350.00 credit");
  await expect(page.getByTestId("max-profit")).toHaveText("+₹19,350.00");
  await expect(page.getByTestId("max-loss")).toHaveText("-₹25,650.00");
  await expect(page.getByTestId("breakevens")).toHaveText("24,542 · 25,058");
  await expect(page.getByTestId("payoff-chart").locator("path.today")).toHaveCount(1);
  await expect(basket.getByTestId("basket-margin")).toHaveText(/^₹[\d,]+\.\d\d$/);
  await expect(basket).toContainText(/hedge saves ₹[\d,]+/);
  await expect(basket).toContainText(/Charges \(est\.\) ₹[\d,]+\.\d\d/);
  await page.screenshot({ path: "test-results/screens/options-iron-fly-1440.png", fullPage: true });

  await basket.getByRole("button", { name: "Place 4 paper orders" }).click();
  await expect(toast(page, /^4 paper orders placed/)).toBeVisible();
  await expect(basket).toHaveCount(0);

  const orders = await page.request.get("/api/v1/orders?broker=fake");
  const placed = ((await orders.json()).orders as { symbol: string; side: string; price: number }[])
    .filter((o) => /^NIFTY29SEP26(24800|25400|24200)(CE|PE)$/.test(o.symbol) && o.price !== null)
    .map((o) => `${o.side} ${o.symbol} ${o.price}`)
    .sort();
  expect(placed).toEqual([
    "BUY NIFTY29SEP2624200PE 6.15",
    "BUY NIFTY29SEP2625400CE 3.1",
    "SELL NIFTY29SEP2624800CE 128.05",
    "SELL NIFTY29SEP2624800PE 139.2",
  ]);
});

test("the chain is live, shades in the money, and switches expiry", async ({ page }) => {
  await signIn(page);
  const rows = chain(page).locator("tbody tr:not(.futures-row)");
  await expect(rows).toHaveCount(21);
  await expect(chain(page).getByTestId("future")).toHaveCount(2);
  // Calls below the underlying and puts above it are in the money.
  await expect(chain(page).locator("tr", { hasText: "24,300" })).toHaveAttribute(
    "data-call-itm",
    "true",
  );
  await expect(chain(page).locator("tr", { hasText: "25,300" })).toHaveAttribute(
    "data-put-itm",
    "true",
  );
  for (const label of ["Spot", "Forward", "ATM", "Days to expiry", "PCR (OI)"]) {
    await expect(page.locator(".stat", { hasText: label }).locator(".value")).not.toHaveText("—");
  }
  await expect(page.getByTestId("spot").locator(".value")).not.toHaveText(
    (await page.getByTestId("spot").locator(".value").textContent()) ?? "",
    { timeout: 5000 },
  );

  const expiries = page.getByRole("group", { name: "Expiry" });
  await expect(expiries.getByRole("button")).toHaveCount(4);
  await expiries.getByRole("button", { name: "6 Oct" }).click();
  await expect(
    chain(page).getByRole("button", { name: /^Buy NIFTY 6th w OCT 24800 CE at/ }),
  ).toBeVisible();
  await expect(page.locator(".stat", { hasText: "Days to expiry" })).toContainText("6 Oct, 15:30");
});

test("picking again adds a lot, the other way takes it off; the basket survives a reload", async ({
  page,
}) => {
  await signIn(page);
  await pick(page, "Buy", "NIFTY SEP 24900 CE");
  await pick(page, "Buy", "NIFTY SEP 24900 CE");
  const leg = page.getByTestId("basket-leg");
  await expect(leg).toContainText("150"); // 2 lots of 75
  await page.reload();
  await expect(leg).toContainText("150");
  await pick(page, "Sell", "NIFTY SEP 24900 CE");
  await expect(leg).toContainText("75");
  await leg.getByRole("button", { name: /^Remove/ }).click();
  await expect(page.getByTestId("basket")).toHaveCount(0);
});

test("a stock without options says so; the underlying picker switches", async ({ page }) => {
  await signIn(page, "/options/NSE/RELIANCE");
  await expect(page.getByRole("heading", { name: "No option chain for RELIANCE" })).toBeVisible();
  await page.getByRole("button", { name: /^Underlying: RELIANCE/ }).click();
  await page.getByRole("option", { name: /NIFTY 50/ }).click();
  await expect(page).toHaveURL(/\/options\/NSE\/NIFTY%2050$/);
  await expect(chain(page)).toBeVisible();
});

for (const width of [1280, 1440, 1920]) {
  test(`option chain at ${width}px: no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    await pick(page, "Sell", "NIFTY SEP 24800 CE");
    await pick(page, "Buy", "NIFTY SEP 25000 CE");
    await expect(page.getByTestId("payoff-chart")).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await page.waitForTimeout(400);
      expect(await noOverflow(page)).toEqual([]);
      await page.screenshot({ path: `test-results/screens/options-${width}-${theme}.png` });
    }
  });
}
