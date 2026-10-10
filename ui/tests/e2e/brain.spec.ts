import { expect, type Page, test } from "@playwright/test";
import { qty, rupees } from "../../src/lib/format";
import { nextLink } from "./links";

// The Brain page over e2e_brain.py's notes: every strategy with its symbols,
// two lessons and a proposal on the straddle, linked to recent days.

const LESSON = "Exit the straddle by 11:00 on expiry day";
const sheet = (page: Page) => page.getByRole("complementary", { name: "Selected note" });
const sheetTitle = (page: Page) => sheet(page).getByRole("heading", { level: 2 });

async function signIn(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(nextLink());
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

/** The canvas has no points to reach by keyboard; the hidden list of notes does. */
async function pick(page: Page, name: string) {
  await page
    .getByRole("navigation", { name: "Notes in the graph" })
    .getByRole("button", { name })
    .focus();
  await page.keyboard.press("Enter");
}

test("proof: Brain opens the graph of the real strategies; a note's links lead on", async ({
  page,
}) => {
  await signIn(page);
  await page
    .getByRole("navigation", { name: "Pages" })
    .getByRole("link", { name: "Brain" })
    .click();
  await expect(page).toHaveURL(/\/brain$/);
  await expect(page.getByTestId("brain-graph").locator("canvas")).toBeVisible();
  await expect(page.getByText(/^\d+ notes · \d+ links$/)).toBeVisible();
  const notes = page.getByRole("navigation", { name: "Notes in the graph" });
  await expect(notes.getByRole("button", { name: "strategy: NIFTY short straddle" })).toHaveCount(
    1,
  );
  await expect(notes.getByRole("button", { name: "symbol: NIFTY 50" })).toHaveCount(1);

  await pick(page, `lesson: ${LESSON}`);
  await expect(sheetTitle(page)).toHaveText(LESSON);
  await expect(page).toHaveURL(/\/brain#les_/);
  await expect(sheet(page).getByText("Not checked yet · Tested after 3 more checks")).toBeVisible();
  await expect(sheet(page).getByText(/^Short straddle losses cluster/)).toBeVisible();

  // A wikilink in the text opens the day it names, which links back.
  await sheet(page).getByRole("link", { name: "the day before" }).click();
  await expect(sheetTitle(page)).toHaveText(/^(Mon|Tue|Wed|Thu|Fri) \d+ \w{3}$/);
  await sheet(page).getByRole("link", { name: LESSON }).click();
  await expect(sheetTitle(page)).toHaveText(LESSON);

  // The strategy's note lists its symbol and leads to the strategy's page.
  await sheet(page).getByRole("link", { name: "NIFTY short straddle" }).click();
  await expect(sheetTitle(page)).toHaveText("NIFTY short straddle");
  await expect(sheet(page).getByRole("link", { name: "NIFTY 50" })).toBeVisible();
  await sheet(page).getByRole("link", { name: "Open strategy" }).click();
  await expect(page.getByRole("heading", { name: "NIFTY short straddle", level: 1 })).toBeVisible();
});

test("a point clicked on the canvas opens its note; Escape closes it", async ({ page }) => {
  await signIn(page);
  await page.goto("/brain");
  const graph = page.getByTestId("brain-graph");
  await expect(graph.locator("canvas")).toBeVisible();
  await page.waitForTimeout(1500); // the layout settles

  const point = await graph.locator("canvas").evaluate((canvas) => {
    const box = canvas.getBoundingClientRect();
    // Whole pixels, where a real click lands.
    for (let y = Math.ceil(box.top) + 20; y < box.bottom - 20; y += 8) {
      for (let x = Math.ceil(box.left) + 20; x < box.right - 20; x += 8) {
        if (document.elementFromPoint(x, y) !== canvas) continue; // under the bar or a control
        canvas.dispatchEvent(new PointerEvent("pointermove", { clientX: x, clientY: y }));
        if (canvas.style.cursor === "pointer") return { x, y };
      }
    }
    return null;
  });
  if (!point) throw new Error("no point found on the graph");
  await page.mouse.click(point.x, point.y);
  await expect(sheetTitle(page)).not.toHaveText("");
  await page.keyboard.press("Escape");
  await expect(sheetTitle(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/brain$/);
});

test("the lists: lessons with their checks, the open proposal counted, days", async ({ page }) => {
  await signIn(page);
  await page.goto("/brain");
  const views = page.getByRole("group", { name: "Brain view" });
  await expect(views.getByRole("button", { name: "Proposals 1" })).toBeVisible();

  await views.getByRole("button", { name: "Lessons" }).click();
  await expect(page).toHaveURL(/\/brain\/lessons$/);
  const lessons = page.getByRole("table", { name: "Lessons" });
  await expect(lessons.getByRole("row")).toHaveCount(3); // head + 2
  const expiry = lessons.getByRole("row").filter({ hasText: LESSON });
  await expect(expiry).toContainText("Hunch");
  await expect(expiry).toContainText("Not checked yet");
  await expect(expiry).toContainText("NIFTY short straddle");
  await expect(lessons.getByRole("row").filter({ hasText: "first 5 minutes" })).toContainText(
    "Every strategy",
  );

  await views.getByRole("button", { name: /Proposals/ }).click();
  const proposal = page.getByRole("table", { name: "Proposals" }).getByRole("row").nth(1);
  await expect(proposal).toContainText("Straddle: exit by 11:00 on expiry");
  await expect(proposal).toContainText("Open");

  await views.getByRole("button", { name: "Days" }).click();
  await expect(page.getByRole("table", { name: "Days" }).getByRole("row")).toHaveCount(5);

  // A row opens the lesson's page, which leads back to its note in the graph.
  await views.getByRole("button", { name: "Lessons" }).click();
  await expiry.click();
  await expect(page).toHaveURL(/\/brain\/lessons\/les_/);
  await expect(page.getByRole("heading", { name: LESSON, level: 1 })).toBeVisible();
  await expect(page.getByText("applies to NIFTY short straddle")).toBeVisible();
  const uses = page.getByRole("region", { name: "Used by" });
  await expect(uses).toContainText("Review · NIFTY short straddle");
  await expect(uses).toContainText("Kept the 11:00 exit on expiry days");
  await page.getByRole("link", { name: "Show in graph" }).click();
  await expect(page).toHaveURL(/\/brain#les_/);
  await expect(sheetTitle(page)).toHaveText(LESSON);
});

interface Fill {
  charges: number | null;
}

test("proof: today's page has the debrief on the trade book's own figures", async ({ page }) => {
  await signIn(page);
  await page.goto("/brain/days");
  await page.getByRole("table", { name: "Days" }).getByRole("row").nth(1).click(); // newest
  await expect(page).toHaveURL(/\/brain\/days\/\d{4}-\d{2}-\d{2}$/);
  const date = new URL(page.url()).pathname.split("/").pop() ?? "";

  await expect(
    page.getByText("Straddle sold into rich IV; one hand trade on HDFCBANK"),
  ).toBeVisible();
  const trades = page.getByRole("table", { name: "Trades and trade-offs" });
  const straddle = trades.getByRole("row").filter({ hasText: "NIFTY short straddle" });
  await expect(straddle).toContainText("Why: Scheduled entry; IV above its 20-day mean");
  await expect(straddle).toContainText("Gamma risk into the afternoon");
  const byHand = trades.getByRole("row").filter({ hasText: "Faded the gap at the open" });
  await expect(byHand).toContainText("HDFCBANK");
  await expect(byHand).toContainText("Claude");
  await expect(byHand).toContainText("Order outside a strategy");
  await expect(page.getByText("Hindsight only")).toBeVisible();
  await expect(page.getByText("Knowable before")).toBeVisible();

  // Every fill of the day is the trade book's, and so are the charges.
  const book = await (
    await page.request.get("/api/v1/trades?broker=fake&period=today&limit=500")
  ).json();
  const charges = book.trades.reduce((sum: number, t: Fill) => sum + (t.charges ?? 0), 0);
  await expect(page.getByTestId("day-fills")).toContainText(qty(book.trades.length));
  await expect(page.getByTestId("day-charges")).toContainText(
    rupees(Math.round(charges * 100) / 100),
  );

  // The day's links: the straddle's strategy, and back to the graph.
  await page.getByRole("link", { name: "Show in graph" }).click();
  await expect(page).toHaveURL(/\/brain#bn_/);
  await expect(sheetTitle(page)).toHaveText(/^(Mon|Tue|Wed|Thu|Fri) \d+ \w{3}$/);
  await sheet(page).getByRole("link", { name: "Open day" }).click();
  await expect(page).toHaveURL(new RegExp(`/brain/days/${date}$`));
});

test("your note saves; an edit from another tab shows both texts", async ({ page }) => {
  await signIn(page);
  const days = await (await page.request.get("/api/v1/brain/notes?kind=day&limit=1")).json();
  const [day] = days.notes;
  await page.goto(`/brain/days/${day.key}`);
  const editor = page.getByRole("textbox", { name: "Your note, in markdown" });

  await page.getByRole("button", { name: "Add a note" }).click();
  await editor.fill("Should have paused the straddle myself.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(editor).toHaveCount(0); // saved, not still being edited
  await expect(page.getByText("Should have paused the straddle myself.")).toBeVisible();

  // Editing starts; meanwhile another tab saves its own text.
  await page.getByRole("button", { name: "Edit" }).click();
  const now = await (await page.request.get(`/api/v1/brain/notes/${day.note_id}`)).json();
  const other = await page.request.patch(`/api/v1/brain/notes/${day.note_id}`, {
    data: { text: "From the other tab", version: now.version },
    headers: { origin: new URL(page.url()).origin }, // as another tab of the app sends it
  });
  expect(other.ok()).toBe(true);
  await editor.fill("Mine, written over it.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const conflict = page.getByRole("alert").filter({ hasText: "changed while you were editing" });
  await expect(conflict).toContainText("From the other tab");
  await page.getByRole("button", { name: "Save mine instead" }).click();
  await expect(editor).toHaveCount(0); // saved, not still being edited
  await expect(page.getByText("Mine, written over it.")).toBeVisible();
  await expect(conflict).toHaveCount(0);

  // A debrief written again meanwhile isn't a conflict: the note saves over it.
  await page.getByRole("button", { name: "Edit" }).click();
  const written = await (await page.request.get(`/api/v1/brain/notes/${day.note_id}`)).json();
  const rewrite = await page.request.put(`/api/v1/brain/days/${day.key}`, {
    data: { ...written.debrief, happened: written.body }, // the same debrief, again
    headers: { origin: new URL(page.url()).origin },
  });
  expect(rewrite.ok()).toBe(true);
  await editor.fill("Kept through a rewrite.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(editor).toHaveCount(0); // saved, not still being edited
  await expect(page.getByText("Kept through a rewrite.")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("proof: owed checks answered move a lesson to tested; retired and reinstated by hand", async ({
  page,
}) => {
  await signIn(page);
  const origin = new URL(page.url()).origin;
  const found = await (
    await page.request.get("/api/v1/brain/notes?kind=lesson&query=first%205%20minutes")
  ).json();
  const [desk] = found.notes;
  const days = await (await page.request.get("/api/v1/brain/notes?kind=day&limit=1")).json();
  const [today] = days.notes;

  // Today's page lists what the desk-wide lesson is owed: today's orders placed by hand.
  await page.goto(`/brain/days/${today.key}`);
  const dayLessons = page.getByRole("region", { name: "Lessons" });
  const owedToday = dayLessons.getByRole("listitem").filter({ hasText: "first 5 minutes" });
  await expect(owedToday.first()).toContainText("Owed");
  await expect(owedToday.first()).toContainText("outside a strategy");

  await page.goto(`/brain/lessons/${desk.note_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(desk.title);
  await expect(page.getByTestId("lesson-held")).toContainText("Not checked yet");
  const owed = page.getByRole("table", { name: "Owed checks" });
  const owing = (await owed.getByRole("row").count()) - 1;
  expect(owing).toBeGreaterThanOrEqual(3);

  // The debrief answers three of them (as an agent would, over the API).
  const note = await (await page.request.get(`/api/v1/brain/notes/${desk.note_id}`)).json();
  for (const check of note.lesson.owed.slice(0, 3)) {
    const answered = await page.request.post(`/api/v1/brain/lessons/${desk.note_id}/checks`, {
      data: {
        order_id: check.order_id,
        outcome: "held",
        observed: "filled after 09:20, spread under 0.05%",
        why: "waited out the opening prints",
      },
      headers: { origin },
    });
    expect(answered.ok()).toBe(true);
  }
  await page.reload();
  await expect(page.locator(".page-head .badge")).toHaveText("Tested");
  await expect(page.getByTestId("lesson-held")).toContainText("3 of 3");
  await expect(page.getByTestId("lesson-next")).toContainText(
    "Rule after 7 more checks that hold.",
  );
  const checks = page.getByRole("table", { name: "Checks since it was written" });
  await expect(checks.getByRole("row")).toHaveCount(4); // head + 3
  await expect(checks.getByRole("row").nth(1)).toContainText("Held");
  await expect(checks.getByRole("row").nth(1)).toContainText("spread under 0.05%");
  await expect(owed.getByRole("row")).toHaveCount(owing - 3 + 1);
  await page.screenshot({ path: "test-results/screens/brain-lesson-1440.png", fullPage: true });

  // Retired by hand, with a reason; then reinstated, and back to its checks.
  await page.getByRole("button", { name: "Retire…" }).click();
  await page.getByRole("textbox", { name: /Why retire it/ }).fill("Only true for index options");
  await page.getByRole("button", { name: "Retire", exact: true }).click();
  await expect(page.locator(".page-head .badge")).toHaveText("Retired");
  await expect(page.getByRole("heading", { name: "Retired by you" })).toBeVisible();
  await expect(page.getByText("“Only true for index options”")).toBeVisible();
  await expect(page.getByText("Retired lessons aren't owed checks.")).toBeVisible();

  await page.getByRole("button", { name: "Reinstate" }).click();
  await expect(page.locator(".page-head .badge")).toHaveText("Tested");
  await expect(page.getByRole("heading", { name: "Reinstated by you" })).toBeVisible();
  await page.getByRole("button", { name: "Let the checks decide" }).click();
  await expect(page.getByRole("heading", { name: "Status from its checks" })).toBeVisible();

  // Today's page shows the answers beside what's still owed.
  await page.goto(`/brain/days/${today.key}`);
  await expect(dayLessons.getByRole("listitem").filter({ hasText: "Held" })).toHaveCount(3);
  await page.setViewportSize({ width: 1280, height: 900 });
  await dayLessons.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/screens/brain-day-lessons-1280.png" });
});

test("proof: reject a proposal with a reason, which search serves; accept another and copy", async ({
  page,
  context,
}) => {
  await signIn(page);
  const origin = new URL(page.url()).origin;
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
  await page.goto("/brain/proposals");
  const views = page.getByRole("group", { name: "Brain view" });
  await expect(views.getByRole("button", { name: "Proposals 1" })).toBeVisible();
  await page.getByRole("table", { name: "Proposals" }).getByRole("row").nth(1).click();
  await expect(page).toHaveURL(/\/brain\/proposals\/prp_/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Straddle: exit by 11:00 on expiry",
  );
  const change = page.getByRole("region", { name: "The change" });
  await expect(change).toContainText("NIFTY short straddle");
  await expect(change.getByRole("listitem").filter({ hasText: LESSON })).toContainText("Hunch");
  await expect(change).toContainText("Two expiry days is a small sample");
  await expect(page.getByText(/^Change strategy NIFTY short straddle \(/)).toBeVisible();

  // Rejected with a reason: final, and served to agents with the proposal.
  const reject = page.getByRole("button", { name: "Reject with reason" });
  await expect(reject).toBeDisabled();
  await page.getByRole("textbox", { name: /Rejecting instead/ }).fill("Keep full-day theta");
  await reject.click();
  await expect(page.locator(".page-head .badge")).toHaveText("Rejected");
  await expect(page.getByText("“Keep full-day theta”")).toBeVisible();
  const found = await (
    await page.request.get("/api/v1/brain/notes?kind=proposal&status=rejected")
  ).json();
  expect(found.notes.map((n: { reason: string }) => n.reason)).toEqual(["Keep full-day theta"]);

  // Another, raised as an agent would, is accepted and its request copied.
  const strategies = await (await page.request.get("/api/v1/strategies")).json();
  const straddle = strategies.strategies.find(
    (s: { name: string }) => s.name === "NIFTY short straddle",
  );
  const raised = await page.request.post("/api/v1/brain/proposals", {
    data: {
      strategy_id: straddle.strategy_id,
      change: "Straddle: combined stop at ₹3,000",
      why: "Two runs lost more than ₹3,000 before the legs' own stops hit.",
      wrong_if: "A tighter stop may cut runs that recover by the close.",
    },
    headers: { origin },
  });
  expect(raised.ok()).toBe(true);
  const other = await raised.json();
  await page.goto(`/brain/proposals/${other.note_id}`);
  await expect(views).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Earlier on this strategy" })).toContainText(
    "“Keep full-day theta”",
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: "test-results/screens/brain-proposal-1280.png", fullPage: true });
  await page.getByRole("button", { name: "Accept and copy" }).click();
  await expect(page.locator(".page-head .badge")).toHaveText("Accepted");
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(other.proposal.request);
  await expect(page.getByRole("region", { name: "Accepted" })).toContainText(
    "Change strategy NIFTY short straddle",
  );

  await page.goto("/brain/proposals");
  await expect(views.getByRole("button", { name: "Proposals", exact: true })).toBeVisible();
});

test("the daily debrief: turned on, asked for now, and a day's rewrite stopped", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/brain/lessons");
  const line = page.getByTestId("debrief-line");
  await expect(line.getByRole("heading", { name: "Daily debrief" })).toBeVisible();
  await page.goto("/brain");
  await expect(page.getByTestId("brain-graph").locator("canvas")).toBeVisible();
  await page.screenshot({ path: "test-results/screens/brain-debrief-off-1440.png" });
  await line
    .getByRole("group", { name: "Debrief time" })
    .getByRole("button", { name: "16:30" })
    .click();
  await line.getByRole("button", { name: "Turn on" }).click();
  await expect(line).toContainText("Debrief after every close at 16:30");
  await expect(line).toContainText(/next \d+ \w{3} 16:30/);
  await page.waitForTimeout(800); // the graph re-frames to its shorter stage
  await page.screenshot({ path: "test-results/screens/brain-debrief-on-1440.png" });
  const schedule = await (await page.request.get("/api/v1/brain/debrief-schedule")).json();
  expect(schedule.at).toBe("16:30");
  await line.getByRole("button", { name: "Turn off" }).click();
  await expect(line.getByRole("button", { name: "Turn on" })).toBeVisible();

  // Today's page asks for its debrief again: a job waits for openticker-serve.
  const days = await (await page.request.get("/api/v1/brain/notes?kind=day&limit=1")).json();
  await page.goto(`/brain/days/${days.notes[0].key}`);
  await page.getByRole("button", { name: "Rewrite debrief" }).click();
  await expect(
    page.getByTestId("toast").filter({ hasText: /^Debrief of .+ asked for/ }),
  ).toBeVisible();

  // It shows on the Agents page as the day's debrief, and is stopped there.
  await page.goto("/agents");
  const waiting = page
    .getByRole("table", { name: "Agent jobs" })
    .getByRole("row")
    .filter({ hasText: "Debrief of" })
    .filter({ hasText: "Waiting" });
  await expect(waiting).toHaveCount(1);
  await waiting.hover();
  await waiting.getByRole("button", { name: "Stop" }).click();
  await expect(
    page.getByTestId("toast").filter({ hasText: /^Debrief of .+ stopped before it started\.$/ }),
  ).toBeVisible();
});

test("proof: the Learning line says how often designs and reviews cited a lesson", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/brain");
  const line = page.getByTestId("learning-line");
  const learning = await (await page.request.get("/api/v1/brain/learning?days=30")).json();
  const could = learning.designs + learning.reviews;
  const cited = learning.designs_citing + learning.reviews_citing;

  // The seed's strategies were designed after the desk's opening lesson, which was cited.
  expect(learning.designs_citing).toBeGreaterThan(0);
  await expect(line).toContainText(
    `Lessons cited in ${Math.round(learning.cite_share * 100)}% of designs and reviews (${cited} of ${could})`,
  );
  await expect(line).toContainText(
    learning.checks_owed === 0 ? "no checks owed" : `${learning.checks_owed} checks owed`,
  );
  await expect(line).toContainText("30 days");
  await page.screenshot({ path: "test-results/screens/brain-learning-1440.png" });
});

test("the settings: kinds and statuses filter the count; find picks a note; they fold away", async ({
  page,
}) => {
  await signIn(page);
  await page.evaluate(() => localStorage.removeItem("ot.brain.display"));
  await page.goto("/brain");
  const settings = page.getByRole("complementary", { name: "Graph settings" });
  const count = page.getByTestId("graph-count");
  await expect(count).toHaveText(/^\d+ notes · \d+ links$/);
  const whole = (await count.textContent()) ?? "";
  const all = Number(whole.split(" ")[0]);

  // Symbols off: fewer notes shown, out of the same whole.
  const symbols = settings.getByRole("button", { name: /^Symbols/ });
  await expect(symbols).toHaveAttribute("aria-pressed", "true");
  await symbols.click();
  await expect(symbols).toHaveAttribute("aria-pressed", "false");
  await expect(count).toHaveText(new RegExp(`^\\d+ of ${all} notes · \\d+ links$`));
  // Every kind off: nothing matches.
  for (const kind of ["Days", "Strategies", "Lessons", "Proposals"]) {
    await settings.getByRole("button", { name: new RegExp(`^${kind}`) }).click();
  }
  await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
  for (const kind of ["Symbols", "Days", "Strategies", "Lessons", "Proposals"]) {
    await settings.getByRole("button", { name: new RegExp(`^${kind}`) }).click();
  }
  await expect(count).toHaveText(whole);
  // Retired lessons start hidden.
  await expect(settings.getByRole("button", { name: /^Retired/ })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  // "/" finds; Enter opens the first match, and the settings fold out of its way.
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("/");
  await expect(settings.getByRole("textbox", { name: "Find a note" })).toBeFocused();
  await page.keyboard.type("first 5");
  await page.keyboard.press("Enter");
  await expect(sheetTitle(page)).toHaveText("No entries in the first 5 minutes");
  await expect(settings.getByRole("button", { name: "Show graph settings" })).toBeVisible();
  await page.waitForTimeout(700); // the sheet slides in
  await page.screenshot({ path: "test-results/screens/brain-settings-folded-1440.png" });
  await page.keyboard.press("Escape");
  await expect(settings.getByRole("button", { name: "Hide graph settings" })).toBeVisible();
  await settings.getByText("Display").click();
  await page.waitForTimeout(700); // the sheet slides out
  await page.screenshot({ path: "test-results/screens/brain-settings-1440.png" });
});

test("Around selection shows the note's neighbourhood by depth; a note's page opens there", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/brain");
  const count = page.getByTestId("graph-count");
  await expect(count).toHaveText(/^\d+ notes/);
  const scope = page.getByRole("group", { name: "Scope" });
  await scope.getByRole("button", { name: "Around selection" }).click();
  await expect(page.getByText("Pick a note to see around it")).toBeVisible();

  await pick(page, "strategy: RELIANCE breakout");
  const depth = page.getByRole("group", { name: "Depth" });
  await depth.getByRole("button", { name: "1" }).click();
  await expect(count).toHaveText(/^\d+ of \d+ notes/);
  const one = Number((await count.textContent())?.split(" ")[0]);
  await depth.getByRole("button", { name: "3" }).click();
  await expect
    .poll(async () => Number((await count.textContent())?.split(" ")[0]))
    .toBeGreaterThan(one);
  await scope.getByRole("button", { name: "Whole brain" }).click();
  await expect(count).toHaveText(/^\d+ notes · /);

  // A lesson's mini graph: its neighbours; a click opens one on the Brain page, around it.
  await page.goto("/brain/lessons");
  await page
    .getByRole("table", { name: "Lessons" })
    .getByRole("row")
    .filter({ hasText: LESSON })
    .click();
  const mini = page.getByTestId("mini-graph");
  await expect(mini.locator("canvas")).toBeVisible();
  await expect(page.getByText(/^\d+ linked notes\. Click one/)).toBeVisible();
  await page.waitForTimeout(800); // the layout settles
  await mini.screenshot({ path: "test-results/screens/brain-mini-1440.png" });
  const point = await mini.locator("canvas").evaluate((canvas) => {
    const box = canvas.getBoundingClientRect();
    // Whole pixels, where a real click lands.
    for (let y = Math.ceil(box.top) + 6; y < box.bottom - 6; y += 4) {
      for (let x = Math.ceil(box.left) + 6; x < box.right - 6; x += 4) {
        canvas.dispatchEvent(new PointerEvent("pointermove", { clientX: x, clientY: y }));
        if (canvas.style.cursor === "pointer") return { x, y };
      }
    }
    return null;
  });
  if (!point) throw new Error("no point found on the mini graph");
  await page.mouse.click(point.x, point.y);
  await expect(page).toHaveURL(/\/brain#/);
  await expect(
    page.getByRole("group", { name: "Scope" }).getByRole("button", { name: "Around selection" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(sheetTitle(page)).not.toHaveText("");
  await expect(count).toHaveText(/^\d+ of \d+ notes/);
});

test("the brain's events are in Activity under Brain", async ({ page }) => {
  await signIn(page);
  await page.goto("/activity");
  await page.getByRole("group", { name: "Kind" }).getByRole("button", { name: "Brain" }).click();
  await expect(page.getByText(/^Proposed for NIFTY short straddle: /).first()).toBeVisible();
  // Answering checks earlier moved the desk's lesson from hunch to tested.
  await expect(page.getByText(/: hunch → tested, held \d+ of \d+$/).first()).toBeVisible();
});
