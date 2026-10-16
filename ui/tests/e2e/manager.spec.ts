import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The desk manager's numbers (ADR 41): the manager sets its own trades' line,
// the user overrides its stop in place, and hands it back.

const home = "test-results/e2e-home";

function manage() {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, "manage"],
    { cwd: "..", stdio: "inherit" },
  );
}

const own = (page: Page) =>
  page
    .getByRole("table", { name: "The manager's numbers" })
    .getByRole("row")
    .filter({ hasText: "Its own trades" });

test("your stop stands over the manager's until you hand it back", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  manage();
  await page.goto(nextLink());
  await page.goto("/manager");
  await expect(page.getByRole("heading", { name: "Manager", level: 1 })).toBeVisible();
  await expect(own(page)).toContainText("Manager");
  await expect(own(page)).toContainText("₹2,00,000");

  await own(page)
    .getByRole("button", { name: /Change Its own trades's stop/ })
    .click();
  await page.keyboard.type("1500");
  await page.keyboard.press("Enter");

  await expect(own(page).locator(".badge")).toHaveText("You");
  await expect(own(page)).toContainText("-₹1,500");
  await expect(own(page)).toContainText("Manager wanted stop -₹2,000");

  await own(page).getByRole("button", { name: "Hand back" }).click();
  await expect(own(page).locator(".badge")).toHaveText("Manager");
  await expect(own(page)).toContainText("-₹2,000");
});

test("today's money shows the market apart from the charges", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  manage();
  await page.goto(nextLink());
  await page.goto("/manager");
  const split = page.locator(".mgr-split");
  await expect(split).toContainText("Market, closed trades");
  await expect(split).toContainText("Market, still open");
  await expect(split).toContainText("Charges and taxes");

  const table = page.getByRole("table", { name: "The manager's numbers" });
  for (const head of ["Market", "Charges", "Today"]) {
    await expect(table.getByRole("columnheader", { name: head, exact: true })).toBeVisible();
  }
  const straddle = table.getByRole("row").filter({ hasText: "NIFTY short straddle" });
  await expect(straddle).toContainText("-₹86.57"); // today's entry charges, nothing closed yet
  const desk = table.getByRole("row").filter({ hasText: "Includes what's still open" });
  await expect(desk).toBeVisible();

  // The narrowest the app is laid out for: the table scrolls inside its tile, if at all.
  await page.setViewportSize({ width: 1280, height: 900 });
  const sideways = await page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, main")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );
  expect(sideways).toEqual([]);
});

test("how it runs: two choices, each opened here, and its looks on the day", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await page.goto("/manager");
  const tile = page.getByTestId("how-it-runs");
  await expect(tile).toContainText("Claude Code");
  await expect(tile.getByRole("figure", { name: "Today's looks on the session" })).toBeVisible();

  const decisive = tile.getByRole("button", { name: /Decisive looks/ });
  const checks = tile.getByRole("button", { name: /Check-ins/ });
  await expect(checks).toBeVisible();
  await decisive.click();
  await expect(decisive).toHaveAttribute("aria-expanded", "true");
  // Every effort level shows in the side column: it wraps, never scrolls sideways.
  const levels = tile.getByRole("group", { name: "Manager: decisive looks effort" });
  expect(await levels.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  // The model box and its effort levels line up edge to edge.
  const edges = async (name: string) =>
    tile
      .getByRole("combobox", { name })
      .first()
      .evaluate((el) => {
        const r = el.getBoundingClientRect();
        return [Math.round(r.left), Math.round(r.right)];
      });
  const track = await levels.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.right)];
  });
  expect(await edges("Manager: decisive looks model")).toEqual(track);
  // Each stat's value fits its card.
  for (const value of await page.locator(".stats .stat .value").all())
    expect(await value.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  await levels.getByRole("button", { name: "High", exact: true }).click();
  await expect(decisive.getByRole("img", { name: "Effort high" })).toBeVisible();
  await checks.click();
  await tile
    .getByRole("group", { name: "Manager: check-ins effort" })
    .getByRole("button", { name: "Low", exact: true })
    .click();
  await expect(checks.getByRole("img", { name: "Effort low" })).toBeVisible();
  const saved = await (await page.request.get("/api/v1/agents/settings")).json();
  const effort = (kind: string) =>
    saved.folders.find((f: { kind: string }) => f.kind === kind).stored.effort;
  expect([effort("manager"), effort("manager-checks")]).toEqual(["high", "low"]);

  // Back to the defaults, for the tests after.
  await tile
    .getByRole("group", { name: "Manager: check-ins effort" })
    .getByRole("button", { name: /^Auto/ })
    .click();
  // Unset, check-ins run as the decisive looks do.
  await expect(checks.getByRole("img", { name: "Effort high" })).toBeVisible();
  await decisive.click();
  await tile
    .getByRole("group", { name: "Manager: decisive looks effort" })
    .getByRole("button", { name: /^Auto/ })
    .click();
  await expect(decisive.getByRole("img", { name: "Effort auto" })).toBeVisible();
});

test("the plan is told what broke since the last close, and shows it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await page.goto("/manager");
  await page.getByRole("button", { name: "Turn on" }).click();
  const told = page.locator(".mgr-told");
  await expect(told).toContainText("Since the last close", { timeout: 20_000 });
  await expect(told).toContainText("Yesterday's close");
  // Each look's tip opens inside the tile, one near the open as much as the close.
  const tile = page.getByTestId("how-it-runs");
  const looks = tile.locator(".mgr-run-look");
  await expect(looks.first()).toBeVisible();
  const box = await tile.boundingBox();
  for (const look of await looks.all()) {
    await look.hover();
    const tip = look.locator(".mgr-run-tip");
    await expect(tip).toHaveCSS("opacity", "1");
    const at = await tip.boundingBox();
    expect(box && at && at.x >= box.x && at.x + at.width <= box.x + box.width).toBe(true);
  }
  await page.getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByRole("button", { name: "Turn on" })).toBeVisible();
});

test("the tape lists its days; a past day opens as it closed and comes back", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await page.goto("/manager");
  const tape = page.getByRole("listbox", { name: "Trading days" });
  const today = tape.getByRole("option", { name: /^Tue 22 Sep/ });
  await expect(today).toHaveAttribute("aria-selected", "true");
  await expect(today).toContainText("Today");

  await tape.getByRole("option", { name: /^Mon 21 Sep/ }).click();
  await expect(page).toHaveURL(/\/manager\/2026-09-21$/);
  await expect(page.getByRole("heading", { name: "Mon 21 Sep" })).toBeVisible();
  await expect(page.getByText(/As it closed/)).toBeVisible();
  // Each day's result is a bar; a past day's money is split, its looks none.
  expect(await tape.locator(".mgr-tape-bar i").count()).toBeGreaterThan(20);
  const thatDay = page.locator(".stat", { hasText: "That day" });
  await expect(thatDay).toContainText("Market, closed trades");
  await expect(thatDay).toContainText("Charges and taxes");
  await expect(page.locator(".stat", { hasText: "Looks" })).toContainText("3");
  await expect(page.locator(".stat", { hasText: "Looks" })).toContainText("$0.28 spent");
  // Its numbers as they stood at the close, read only, each with what changed it.
  const lines = page.getByRole("table", { name: "The manager's numbers that day" });
  await expect(lines.locator(".amount-edit")).toHaveCount(0);
  const desk = lines.getByRole("row", { name: /Desk/ });
  await expect(desk).toContainText("-₹30,000");
  await expect(desk).toContainText(
    "15:36 stop -₹20,000 by the manager: a smaller desk tomorrow, for the next day",
  );
  await expect(
    lines.getByRole("row").filter({ hasText: "11:20 stop -₹4,000 by you" }),
  ).toContainText("You");
  await expect(page.locator(".stat", { hasText: "Given to strategies" })).toContainText(
    "₹2,00,000",
  );
  await expect(page.locator(".stat", { hasText: "Stops crossed" })).toContainText("of 2");
  // Its decisions, how it ran and its plan that day; the brain's day one click away.
  const decided = page.locator(".mgr-decisions > li");
  await expect(decided).toHaveCount(3);
  await expect(decided.first()).toContainText("A smaller desk stop tomorrow");
  const ran = page.getByTestId("how-it-ran");
  await expect(ran.getByRole("figure", { name: "That day's looks on the session" })).toBeVisible();
  await expect(ran.locator(".mgr-run-look")).toHaveCount(3);
  await expect(ran).toContainText("× 2");
  await expect(ran).toContainText("$0.28");
  const plan = page
    .locator(".tile")
    .filter({ has: page.getByRole("heading", { name: "The plan" }) });
  await expect(plan.locator(".mgr-plan-headline")).toContainText("nothing new starts");
  // Each call in its group, with why; what it watched.
  const runs = plan.locator('.mgr-plan-group[data-call="runs"]');
  await expect(runs.locator(".mgr-plan-item")).toHaveCount(1);
  await expect(runs).toContainText("1.8x its median losing run");
  await expect(plan.locator('.mgr-plan-group[data-call="sits_out"]')).toContainText(
    "Its own trades",
  );
  await expect(plan.locator(".mgr-plan-watch")).toContainText("RELIANCE holding has no stop");
  await expect(page.getByText("Not debriefed")).toBeVisible();
  await expect(page.getByRole("link", { name: "The day in the brain ›" }).first()).toHaveAttribute(
    "href",
    "/brain/days/2026-09-21",
  );
  await tape.getByRole("option", { name: /^Fri 18 Sep/ }).hover();
  await expect(page.locator(".mgr-tape-sum")).toContainText("Fri 18 Sep");
  await expect(page.locator(".mgr-tape-sum")).toContainText("The manager was off");
  await page.mouse.move(0, 0);
  await expect(page.locator(".mgr-tape-sum")).toContainText("Days it managed");

  await page.keyboard.press("ArrowLeft"); // Friday, over the weekend
  await expect(page).toHaveURL(/\/manager\/2026-09-18$/);
  await page.getByRole("button", { name: "The day after" }).click();
  await expect(page).toHaveURL(/\/manager\/2026-09-21$/);

  await page.getByRole("button", { name: "Back to today" }).click();
  await expect(page).toHaveURL(/\/manager$/);
  await expect(page.getByRole("button", { name: "Turn on" })).toBeVisible();
  await page.goto("/manager/2026-09-22");
  await expect(page).toHaveURL(/\/manager$/);
});

test("a day it was off, a day further back, and days there weren't", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  // A day it was off: the desk's money stands; no numbers, decisions or looks.
  await page.goto("/manager/2026-09-18");
  await expect(page.getByText(/The manager was off this day/)).toBeVisible();
  await expect(page.locator(".stat", { hasText: "That day" })).toContainText("Charges and taxes");
  await expect(page.getByText(/No numbers that day/)).toBeVisible();
  await expect(page.getByText("Nothing that day: it didn't run.")).toBeVisible();
  await expect(page.getByTestId("how-it-ran")).toHaveCount(0);
  await expect(page.getByText("No plan: it wasn't on.")).toBeVisible();

  // A day before the tape's reach: the tape moves to it.
  await page.getByLabel("A day to open").fill("2026-08-03");
  await expect(page).toHaveURL(/\/manager\/2026-08-03$/);
  const tape = page.getByRole("listbox", { name: "Trading days" });
  await expect(tape.getByRole("option", { name: /^Mon 3 Aug/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(tape.getByRole("option", { name: /^Tue 22 Sep/ })).toHaveCount(0);

  // A weekend and a day to come say why there is nothing.
  await page.goto("/manager/2026-09-20");
  await expect(page.getByText(/wasn't a trading day/).first()).toBeVisible();
  await page.goto("/manager/2026-09-30");
  await expect(page.getByText(/hasn't happened yet/).first()).toBeVisible();
});
