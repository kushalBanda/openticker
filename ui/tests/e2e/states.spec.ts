import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Every page when the server can't answer (DESIGN.md: every state designed):
// each says what didn't load, in place of what would have been there, and
// none is left on a skeleton or a blank ground. The sign-in check still
// answers, as it would with one broken route.

const ROUTES = [
  "/",
  "/watchlist",
  "/options",
  "/positions",
  "/orders",
  "/trades",
  "/strategies",
  "/strategies/nowhere",
  "/scripts",
  "/scripts/nowhere",
  "/agents",
  "/activity",
  "/settings",
  "/symbols/NSE/RELIANCE",
];

const name = (path: string) => path.replace(/^\/$/, "/dashboard").slice(1).replaceAll("/", "-");

async function failEverything(page: Page) {
  await page.route(/\/api\/v1\/(?!session\b)/, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "The server is unavailable" }),
    }),
  );
}

test("every page says what didn't load when the server can't answer", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  const crashes: string[] = [];
  page.on("pageerror", (error) => crashes.push(error.message));

  await page.goto(nextLink());
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await failEverything(page);

  for (const path of ROUTES) {
    await page.goto(path);
    await expect.soft(page.getByRole("heading", { level: 1 }), path).toBeVisible();
    await expect.soft(page.locator(".skeleton"), path).toHaveCount(0, { timeout: 10_000 });
    await expect
      .soft(page.locator("main"), path)
      .toContainText(/didn't load|The server is unavailable|isn't there/i);
    await page.screenshot({ path: `test-results/screens/error-${name(path)}.png`, fullPage: true });
  }
  expect(crashes).toEqual([]);
});

// The market closed, no broker logged in, the broker's session expired: the
// stream's status says which (ADR 32), rewritten here on its way in. With no
// broker nothing ticks, so ticks are dropped too.
const FEEDS = {
  closed: { market_open: false, state: "closed" },
  "no-broker": { broker_connected: false, broker_expires_at: null, state: "no-broker" },
  expired: {
    broker_connected: false,
    broker_expires_at: "2026-09-22T00:30:00Z",
    state: "no-broker",
  },
} as const;

for (const [feed, change] of Object.entries(FEEDS)) {
  test(`every page with ${feed === "closed" ? "the market closed" : feed}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    const crashes: string[] = [];
    page.on("pageerror", (error) => crashes.push(error.message));
    await page.routeWebSocket(/\/api\/v1\/stream/, (browser) => {
      const server = browser.connectToServer();
      server.onMessage((raw) => {
        const message = JSON.parse(String(raw));
        if (message.type === "tick" && feed !== "closed") return;
        if (message.type === "status") message.feed = { ...message.feed, ...change };
        browser.send(JSON.stringify(message));
      });
    });

    await page.goto(nextLink());
    const bar = page.locator(".statusbar");
    if (feed === "closed") await expect(bar).toContainText("Market closed");
    if (feed === "no-broker")
      await expect(page.getByTestId("price-source")).toHaveText("No broker");
    if (feed === "expired") await expect(page.getByTestId("price-source")).toHaveText(/expired/);

    for (const path of ROUTES.filter((p) => !p.endsWith("nowhere"))) {
      await page.goto(path);
      await expect.soft(page.getByRole("heading", { level: 1 }), path).toBeVisible();
      await expect.soft(page.locator(".skeleton"), path).toHaveCount(0, { timeout: 10_000 });
      await page.screenshot({
        path: `test-results/screens/${feed}-${name(path)}.png`,
        fullPage: true,
      });
    }
    expect(crashes).toEqual([]);
  });
}
