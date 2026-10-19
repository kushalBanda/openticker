import { expect, type Locator, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Scripts (ADR 25): three hosted scripts seeded by e2e_hosted.py.
// rel_trail.py is real: started and stopped from this page, its log
// followed live while it runs. gap_scanner.py finished cleanly; the
// content assertions below are seeded facts, not live values.

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/scripts");
  await expect(page.getByRole("heading", { name: "Scripts", level: 1 })).toBeVisible();
}

const table = (page: Page) => page.getByRole("table", { name: "Scripts" });
const row = (page: Page, name: string): Locator =>
  table(page).getByRole("row").filter({ hasText: name });
const toast = (page: Page, text: string) => page.getByTestId("toast").filter({ hasText: text });

test("lists the three seeded scripts: state, schedule, last run, runtime, memory, orders", async ({
  page,
}) => {
  await signIn(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Scripts (3)");
  await expect(
    page.getByText("256 MB of memory and 60 CPU minutes a run", { exact: false }),
  ).toBeVisible();

  const trail = row(page, "rel_trail.py");
  await expect(trail).toContainText("Stopped");
  await expect(trail).toContainText("Mon–Fri 09:16–15:15");
  await expect(trail).toContainText("09:16:00, stopped");
  await expect(trail).toContainText("42m 00s");
  await expect(trail).toContainText("84 / 256 MB");
  // Settings' proof test (runs before this project) resets the paper
  // account, wiping every order: all three scripts read 0 today.
  await expect(trail.getByRole("cell").last()).toHaveText("0");

  const gaps = row(page, "gap_scanner.py");
  await expect(gaps).toContainText("Finished");
  await expect(gaps).toContainText("Mon–Fri 09:10");
  await expect(gaps).toContainText("09:10:00, exit 0");
  await expect(gaps).toContainText("42s");
  await expect(gaps).toContainText("61 / 256 MB");
  await expect(gaps.getByRole("cell").last()).toHaveText("0");

  const scalp = row(page, "banknifty_scalp.py");
  await expect(scalp).toContainText("Failed");
  await expect(scalp).toContainText("only when started");
  await expect(scalp).toContainText("yesterday 10:02, memory limit");
  await expect(scalp).toContainText("3m 11s");
  await expect(scalp).toContainText("257 / 256 MB"); // over the limit
  await expect(scalp.getByRole("cell").last()).toHaveText("0");
});

test("schedule a script: change its days and stop time, then turn it off", async ({ page }) => {
  await signIn(page);
  await row(page, "gap_scanner.py").getByRole("link", { name: "gap_scanner.py" }).click();
  await expect(page.getByRole("heading", { name: "gap_scanner.py", level: 1 })).toBeVisible();
  await expect(page.getByText("Mon–Fri 09:10", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Schedule…" }).click();
  const dialog = page.getByRole("dialog", { name: "Schedule gap_scanner.py" });
  const start = dialog.getByRole("group", { name: "Start", exact: true });
  const stop = dialog.getByRole("group", { name: "Stop (optional)" });
  await expect(start).toHaveAttribute("data-value", "09:10");
  await expect(stop).toHaveAttribute("data-value", "");
  for (const day of ["Mon", "Tue", "Wed", "Thu", "Fri"]) {
    await expect(dialog.getByRole("button", { name: day })).toHaveAttribute("aria-pressed", "true");
  }
  await expect(dialog.getByRole("button", { name: "Sat" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  await dialog.getByRole("button", { name: "Fri" }).click(); // Mon-Thu only
  // Typed as on a clock: the hour fills, then the minutes.
  await stop.getByRole("spinbutton", { name: "Hour" }).focus();
  await page.keyboard.type("1000");
  await expect(stop).toHaveAttribute("data-value", "10:00");
  await expect(dialog.getByRole("slider", { name: "Stop on the session" })).toBeVisible();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toast(page, "gap_scanner.py's schedule saved.")).toBeVisible();
  await expect(page.getByText("Mon, Tue, Wed, Thu 09:10–10:00", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Schedule…" }).click();
  await page.getByRole("button", { name: "Turn off" }).click();
  await expect(toast(page, "gap_scanner.py runs only when started now.")).toBeVisible();
  await expect(page.locator("p.note").filter({ hasText: "Runs only when started" })).toBeVisible();
});

test("proof: start rel_trail.py from the page and watch its log grow, then stop it", async ({
  page,
}) => {
  await signIn(page);
  const trail = row(page, "rel_trail.py");
  await trail.hover();
  await trail.getByRole("button", { name: "Start" }).click();
  await expect(toast(page, "Starting rel_trail.py: it runs within a second.")).toBeVisible();
  await expect(trail).toContainText("Running", { timeout: 5_000 });

  await trail.getByRole("link", { name: "rel_trail.py" }).click();
  await expect(page.getByRole("heading", { name: "rel_trail.py", level: 1 })).toBeVisible();
  await expect(page.locator(".page-head")).toContainText("Running");

  const log = page.getByTestId("code-log");
  await expect(log).toContainText("watching RELIANCE; trigger 2,915.00", { timeout: 5_000 });
  await expect(page.locator(".live-dot")).toBeVisible();
  const first = await log.innerText();
  await expect
    .poll(async () => (await log.innerText()).length, { timeout: 5_000 })
    .toBeGreaterThan(first.length);

  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(
    toast(page, "Stopping rel_trail.py: killed if it hasn't ended in 5 seconds."),
  ).toBeVisible();
  await expect(page.locator(".page-head")).toContainText("Stopped", { timeout: 9_000 });
});
