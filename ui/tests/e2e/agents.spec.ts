import { expect, type Locator, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Agents (ADR 29, ADR 35): the MCP clients e2e_hosted.py seeded (Claude Code,
// Codex) and two review jobs — RELIANCE breakout waiting, BANKNIFTY iron
// condor already timed out — and e2e_brain.py's debrief of today, finished. The proof stops the waiting one; starting a real
// review would need an actual coding agent binary, which this suite doesn't have.

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/agents/jobs");
  await expect(page.getByRole("heading", { name: "Agents", level: 1 })).toBeVisible();
}

const clientRow = (page: Page, name: string): Locator =>
  page.getByRole("table", { name: "Connected agents" }).getByRole("row").filter({ hasText: name });
const jobRow = (page: Page, name: string): Locator =>
  page.getByRole("table", { name: "Agent jobs" }).getByRole("row").filter({ hasText: name });
const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });
const kv = (page: Page) =>
  page.locator(".tile").filter({ hasText: "Review jobs" }).locator("dl.kv");
const kvValue = (page: Page, label: string): Locator =>
  kv(page).locator("dt", { hasText: label }).locator("xpath=following-sibling::dd[1]");

test("shows the connected clients, the review settings, and both seeded jobs", async ({ page }) => {
  await signIn(page);

  // Claude Code's seeded row (212 calls, get_positions) is the same one
  // other specs' real agent calls update as they run before this project,
  // so only its shape is checked here, not its seeded numbers.
  const claude = clientRow(page, "Claude Code");
  await expect(claude).toContainText("stdio");
  await expect(claude).toContainText(/\d+ calls today/);
  await expect(claude).toContainText(/\d+ in all/);

  const codex = clientRow(page, "Codex");
  await expect(codex).toContainText("stdio · 0.41.0");
  await expect(codex).toContainText("place_order");
  await expect(codex).toContainText("18 calls today");
  await expect(codex).toContainText("18 in all");

  await expect(page.getByText("claude mcp add openticker -- uv run openticker-mcp")).toBeVisible();
  await expect(page.getByText("codex mcp add openticker -- uv run openticker-mcp")).toBeVisible();

  await expect(kvValue(page, "Harness")).toHaveText("Claude Code");
  await expect(kvValue(page, "Running now")).toHaveText("0");
  await expect(kvValue(page, "Waiting")).toHaveText("1");
  // Today's debrief, and the review the workspace spec's proof runs when the
  // app project went first (this project depends on it; alone, it didn't).
  await expect(page.getByTestId("jobs-today")).toHaveText(/^[12] of 20$/);
  await expect(kvValue(page, "Time limit")).toHaveText("15 min a job");

  // Brain's proof asked for another and stopped it before this ran.
  const debrief = jobRow(page, "Debrief of").filter({ hasText: "Finished" });
  await expect(debrief).toHaveCount(1);
  await debrief.getByRole("link", { name: /^Debrief of / }).click();
  await expect(page).toHaveURL(/\/brain\/days\/\d{4}-\d{2}-\d{2}$/);
  await page.goBack();

  const reliance = jobRow(page, "RELIANCE breakout").first();
  await expect(reliance).toContainText("Waiting");
  await expect(reliance).toContainText("asked by you");
  await expect(reliance.getByRole("button", { name: "Stop" })).toBeVisible();

  // Two jobs share this name: the seeded timed-out one and an older,
  // finished one from the strategies fixture (`.first()`: newest first).
  const condor = jobRow(page, "BANKNIFTY iron condor").first();
  await expect(condor).toContainText("Timed out");
  await expect(condor).toContainText("asked by Codex");
  await expect(condor).toContainText("15m 00s");
  // Ended jobs have no action pill: the row itself opens the job (below).
  await expect(condor.getByRole("button")).toHaveCount(0);
});

test("a row opens its job: a timed-out one shows what it printed", async ({ page }) => {
  await signIn(page);
  await jobRow(page, "BANKNIFTY iron condor").first().click();
  const dialog = page.getByRole("dialog", { name: "Review job" });
  await expect(dialog).toContainText("still running after 15 minutes");
  await expect(dialog).toContainText("It printed nothing.");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("a finished review says what ran: harness, model, effort, tokens and cost", async ({
  page,
}) => {
  await signIn(page);
  await jobRow(page, "BANKNIFTY iron condor").filter({ hasText: "Finished" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Review job" });
  // Read from the run's stream-json by the harness's own parser (e2e_strategies.py).
  await expect(
    dialog.getByText("Claude Code · claude-opus-5-5 · high · 55.1k tokens · $0.42"),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("proof: stop the waiting review job before it ever starts", async ({ page }) => {
  await signIn(page);
  const reliance = jobRow(page, "RELIANCE breakout").first();
  await expect(kvValue(page, "Waiting")).toHaveText("1");
  await reliance.hover();
  await reliance.getByRole("button", { name: "Stop" }).click();
  await expect(toast(page, "Review of RELIANCE breakout stopped before it started.")).toBeVisible();
  await expect(reliance).toContainText("Stopped", { timeout: 5_000 });
  await expect(reliance.getByRole("button", { name: "Stop" })).toHaveCount(0);
  await expect(kvValue(page, "Waiting")).toHaveText("0");
});
