import { execFileSync } from "node:child_process";
import { expect, type Locator, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Settings (ADR 33, ADR 37). Runs last (playwright.config.ts): it logs the
// broker out and in, and wipes the paper account.

const home = "test-results/e2e-home";

function agent(what: "end-runs") {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.fixtures.e2e_agent", "--home", `ui/${home}`, what],
    { cwd: "..", stdio: "inherit" },
  );
}

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
}

async function hold(page: Page, button: Locator) {
  // Held where the button is once the page has stopped moving: a section
  // above that loads late would slide it out from under the pointer.
  await page.waitForLoadState("networkidle");
  await button.scrollIntoViewIfNeeded();
  await button.hover();
  await page.mouse.down();
  await page.waitForTimeout(1400);
  await page.mouse.up();
}

const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });
const broker = (page: Page) => page.locator("#broker");

test("Agents: a folder's effort saves, runs a day steps, and Reset goes back to the environment", async ({
  page,
}) => {
  await signIn(page);
  const agents = page.locator("#agents");
  await agents.scrollIntoViewIfNeeded();
  await expect(agents.getByRole("radio", { name: /Claude Code/ })).toBeChecked();
  // Both on the e2e server's PATH, each with its version (tests/fixtures/fake_*.py).
  await expect(agents.locator("label", { hasText: "Claude Code" })).toContainText(
    "Ready · 2.1.296",
  );
  await expect(agents.locator("label", { hasText: "Codex" })).toContainText("Ready · 0.48.0");
  // Each agent by its own mark, not a radio dot.
  for (const name of ["Claude Code", "Codex"]) {
    await expect(
      agents.locator("label", { hasText: name }).locator("img.harness-logo"),
    ).toBeVisible();
  }

  const reviews = agents.getByRole("button", { name: /Reviews/ });
  await expect(reviews).toContainText("Agent's default");
  await reviews.click();
  await expect(reviews).toHaveAttribute("aria-expanded", "true");
  await agents
    .getByRole("group", { name: "Reviews effort" })
    .getByRole("button", { name: "High", exact: true })
    .click();
  await expect(toast(page, "Saved")).toBeVisible();
  await expect(reviews).toContainText("Default model · High");
  await agents.getByRole("combobox", { name: "Reviews model" }).click();
  // Named as Claude Code lists them, with what each is for and what it runs.
  const opus = page.getByRole("option", { name: /^Opus 5\.5/ });
  await expect(opus).toContainText("claude-opus-5-5");
  await expect(opus).toContainText("For complex work and everyday tasks");
  await page.screenshot({ path: "test-results/screens/settings-agents-models-1440.png" });
  await opus.click();
  await expect(reviews).toContainText("Opus 5.5 · High");
  await expect(agents.getByText(/Runs claude-opus-5-5 today/)).toBeVisible();
  await agents.screenshot({ path: "test-results/screens/settings-agents-1440.png" });

  const runs = agents.locator(".st-count");
  const before = Number(await runs.textContent());
  await agents.getByRole("button", { name: "More runs a day" }).click();
  await expect(runs).toHaveText(String(before + 1));

  await agents.getByRole("button", { name: "Reset to environment" }).click();
  await expect(toast(page, "Agent settings reset to the environment")).toBeVisible();
  await expect(reviews).toContainText("Agent's default");
  await expect(runs).toHaveText(String(before));
});

test("Agents: the manager's check-ins are set apart from its decisive looks", async ({ page }) => {
  await signIn(page);
  const agents = page.locator("#agents");
  await agents.scrollIntoViewIfNeeded();
  await expect(agents.getByRole("button", { name: /Manager: decisive looks/ })).toBeVisible();
  const checks = agents.getByRole("button", { name: /Manager: check-ins/ });
  await checks.click();
  await agents
    .getByRole("group", { name: "Manager: check-ins effort" })
    .getByRole("button", { name: "Low", exact: true })
    .click();
  await expect(toast(page, "Saved")).toBeVisible();
  await expect(checks).toContainText("Low");

  const stored = await page.request.get("/api/v1/agents/settings");
  const folders: { kind: string; stored: { effort: string | null } }[] = (await stored.json())
    .folders;
  expect(folders.find((f) => f.kind === "manager-checks")?.stored.effort).toBe("low");
  expect(folders.find((f) => f.kind === "manager")?.stored.effort).toBeNull();

  await agents.getByRole("button", { name: "Reset to environment" }).click();
  await expect(toast(page, "Agent settings reset to the environment")).toBeVisible();
});

test("proof: disconnect, then connect through the broker's login and its redirect", async ({
  page,
}) => {
  await signIn(page);
  await broker(page).getByRole("button", { name: "Disconnect" }).click();
  await expect(toast(page, "Fake disconnected")).toBeVisible();
  await expect(broker(page).getByText("Not connected")).toBeVisible();
  await expect(
    page.locator("#instruments").getByRole("button", { name: "Connect to sync" }),
  ).toBeDisabled();

  await broker(page).getByRole("button", { name: "Log in to Fake" }).click();
  await expect(page).toHaveURL(/localhost:8752\/connect\/login/); // the broker's own site
  await page.getByRole("link", { name: "Log in" }).click();

  await expect(page).toHaveURL(/127\.0\.0\.1:8751\/settings$/); // flag read and cleared
  await expect(toast(page, "Fake connected")).toBeVisible();
  await expect(broker(page).getByText("Connected", { exact: true })).toBeVisible();
  await expect(broker(page)).toContainText("Last login");
  await page.getByRole("link", { name: "Activity" }).first().click();
  await expect(
    page
      .getByRole("table", { name: "Activity" })
      .getByRole("row")
      .filter({ hasText: "Fake connected" }),
  ).toContainText("You");
});

test("a new key is shown once, then revoked with the hold", async ({ page }) => {
  await signIn(page);
  const keys = page.locator("#keys");
  await keys.getByRole("button", { name: "Create key" }).click();
  await keys.getByRole("textbox", { name: "Key name" }).fill("laptop");
  await keys.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByTestId("new-key")).toContainText("shown this once");
  await expect(page.getByTestId("new-key")).toContainText("otk_");
  const row = keys.getByRole("row").filter({ hasText: "laptop" });
  await expect(row).toContainText("Full");

  await hold(page, row.getByRole("button", { name: "Hold to revoke (press and hold)" }));
  await expect(toast(page, "Key laptop revoked")).toBeVisible();
  await expect(row).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("new-key")).toHaveCount(0); // never shown again
});

test("proof: reset refused while a strategy runs, then succeeds", async ({ page }) => {
  await signIn(page);
  const zone = page.getByTestId("reset-zone");
  const button = zone.getByRole("button", { name: "Hold to reset (press and hold)" });
  await expect(button).toBeDisabled();
  await zone.getByRole("textbox", { name: "Type RESET to confirm" }).fill("RESET");
  await expect(button).toBeEnabled();

  await hold(page, button);
  const refusal = zone.getByRole("alert");
  await expect(refusal).toContainText("Stop strategy NIFTY short straddle");
  await expect(refusal).toContainText("first");
  await page.setViewportSize({ width: 1440, height: 900 });
  await zone.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/screens/settings-reset-refused-1440.png" });

  agent("end-runs");
  await hold(page, button);

  await expect(toast(page, "Paper account reset to ₹25,00,000.00")).toBeVisible();
  await expect(refusal).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Portfolio" })
    .click();
  await expect(page.getByRole("table", { name: "Positions" })).toHaveCount(0);

  // The brain is kept: today's debriefed page keeps its trades and figures.
  const days = await (await page.request.get("/api/v1/brain/notes?kind=day&limit=1")).json();
  await page.goto(`/brain/days/${days.notes[0].key}`);
  await expect(page.getByText(/Kept from before the paper account was reset/)).toBeVisible();
  await expect(page.getByTestId("day-fills")).not.toContainText(/^Fills0$/);
  const trades = page.getByRole("table", { name: "Trades and trade-offs" });
  await expect(trades.getByRole("row").filter({ hasText: "NIFTY short straddle" })).toContainText(
    "Scheduled entry",
  );
});

test("theme: Settings and the status bar agree", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await signIn(page);
  const html = page.locator("html");
  const theme = page.getByRole("group", { name: "Theme" });

  await expect(page.getByRole("link", { name: "TradingView Lightweight Charts™" })).toHaveAttribute(
    "href",
    "https://www.tradingview.com/",
  );
  await theme.getByRole("button", { name: "Light" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(theme.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
  await theme.getByRole("button", { name: "System" }).click();
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "System" }),
  ).toHaveAttribute("aria-pressed", "true");
});
