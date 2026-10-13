import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// The Agents workspace (ADR 40): chats with the user's coding agent, each
// message run by the server's chat lane. Here Claude Code is
// tests/fixtures/fake_claude.py, which answers by repeating the message.

async function signIn(page: Page) {
  await page.goto(nextLink());
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "Agents", level: 1 })).toBeVisible();
}

const noOverflow = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".aw, .aw-rail, .aw-pane, .aw-thread")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

test("a chat reads as turns with folded steps, and a follow-up resumes it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await expect(page.getByRole("heading", { name: "What should we look into?" })).toBeVisible();

  const rail = page.getByRole("navigation", { name: "Chats" });
  await rail
    .getByRole("link", { name: /Why did expiry days lose\?/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/agents\/thr_e2e$/);

  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByRole("heading", { name: "Why did expiry days lose?" })).toBeVisible();
  await expect(chat.getByText("NIFTY short straddle").first()).toBeVisible();
  await expect(chat.getByText(/Four of the five expiry-day losses/)).toBeVisible();
  await expect(
    chat.getByText("Claude Code · claude-opus-5-5 · high · 38.4k tokens · $0.07"),
  ).toBeVisible();

  // Steps are folded behind "Worked for 41s" and open on a click.
  const worked = chat.getByRole("button", { name: /Worked for 41s/ });
  await expect(chat.locator("code", { hasText: "get_strategy_runs" })).toHaveCount(0);
  await worked.click();
  await expect(worked).toHaveAttribute("aria-expanded", "true");
  await expect(chat.locator("code", { hasText: "get_strategy_runs" })).toBeVisible();
  await expect(chat.getByText("notes/NIFTY short straddle.md · +3 lines")).toBeVisible();

  const box = chat.getByRole("textbox", { name: "Message" });
  await box.fill("And on non-expiry days?");
  await box.press("Enter");
  await expect(chat.getByText("And on non-expiry days?", { exact: true })).toBeVisible();
  await expect(box).toHaveValue("");
  await expect(chat.getByText("You asked: And on non-expiry days? (resumed 5f0c2a1e)")).toBeVisible(
    { timeout: 15_000 },
  );
  await expect(
    chat.getByText(/Claude Code · claude-opus-5-5 · 1\.5k tokens · \$0\.01/),
  ).toBeVisible();

  expect(await noOverflow(page)).toEqual([]);
});

test("a new chat runs its first message, then continues the same conversation", async ({
  page,
}) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("What ran today?");
  await box.press("Enter");

  await expect(page).toHaveURL(/\/agents\/thr_[0-9a-f]+$/);
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByRole("heading", { name: "What ran today?" })).toBeVisible();
  await expect(chat.getByText("You asked: What ran today?", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await expect(chat.getByRole("button", { name: /Worked for/ })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Chats" }).getByRole("link", { name: /What ran today\?/ }),
  ).toBeVisible();

  const follow = chat.getByRole("textbox", { name: "Message" });
  await expect(follow).toBeEnabled();
  await follow.fill("And yesterday?");
  await follow.press("Enter");
  await expect(chat.getByText(/You asked: And yesterday\? \(resumed [0-9a-f]{8}\)/)).toBeVisible({
    timeout: 15_000,
  });
});

test("the picker chooses the next message's model and effort, and the turn records them", async ({
  page,
}) => {
  await signIn(page);
  const picker = page.getByRole("button", { name: /^Model and effort/ });
  await picker.click();
  const menu = page.getByRole("menu", { name: "Model and effort" });
  // Effort beside the models, in view without scrolling past them.
  await expect(menu.getByRole("menuitemradio", { name: "Max" })).toBeInViewport();
  await page.waitForTimeout(300);
  await page.screenshot({ path: "test-results/screens/agents-choice-picker-1440.png" });
  // Max picked on the default model, then a model that doesn't take it: let go.
  await menu.getByRole("menuitemradio", { name: "Max" }).click();
  await expect(picker).toContainText("Max");
  await menu.getByRole("menuitemradio", { name: /^Haiku 5\.5/ }).click();
  await expect(menu.getByRole("menuitemradio", { name: "Max" })).toHaveCount(0);
  await expect(menu.getByText("Effort · Haiku 5.5")).toBeVisible();
  await expect(picker).toContainText("Auto");
  await menu.getByRole("menuitemradio", { name: "Low" }).click();
  await page.keyboard.press("Escape");
  await expect(picker).toHaveAccessibleName("Model and effort: Haiku 5.5, Low");
  await page.screenshot({ path: "test-results/screens/agents-choice-button-1440.png" });

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Which model answers?");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByText(/Claude Code · claude-haiku-5-5 · low · 1\.5k tokens/)).toBeVisible({
    timeout: 15_000,
  });
  // The harness is the chat's from its first message.
  await expect(chat.getByTitle("Fixed after the first message").first()).toContainText(
    "Claude Code",
  );
});

test("steps arrive while the agent works, and Stop ends the turn", async ({ page }) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Look slowly at every quote");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/agents\/thr_[0-9a-f]+$/);

  const chat = page.getByRole("region", { name: "Chat" });
  // Unfolded while it runs, counting up; each step shows as the stream sends it.
  const working = chat.getByRole("button", { name: /Working for \d+s/ });
  await expect(working).toBeVisible({ timeout: 15_000 });
  await expect(working).toHaveAttribute("aria-expanded", "true");
  await expect(chat.locator("code", { hasText: "list_strategies" })).toBeVisible();
  await expect(chat.getByText("symbol=STEP1")).toBeVisible({ timeout: 10_000 });
  // A step every 1.5 s, twenty in all: however late the page looked, later
  // steps are still to come, and they arrive while it watches.
  const seen = await chat.getByText(/^symbol=STEP\d+$/).count();
  expect(seen).toBeLessThan(18);
  await expect(chat.getByText(`symbol=STEP${seen + 2}`, { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(chat.getByText(/You asked:/)).toHaveCount(0);

  await chat.getByRole("button", { name: "Stop" }).click();
  await expect(chat.getByRole("alert").filter({ hasText: "stopped by ui" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(chat.getByRole("button", { name: "Send" })).toBeVisible();
  await expect(chat.getByRole("button", { name: /Worked for \d+s/ })).toBeVisible();
});

test("proof: a review runs as a chat, continues as one, and is filed under its strategy", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/strategies");
  await page.getByRole("link", { name: "SBIN mean reversion" }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("SBIN mean reversion");
  await page.getByRole("button", { name: "Review now" }).click();

  await page.goto("/agents");
  const rail = page.getByRole("navigation", { name: "Chats" });
  await rail
    .getByRole("link", { name: /^Review of SBIN mean reversion/ })
    .first()
    .click();
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByRole("heading", { name: "Review of SBIN mean reversion" })).toBeVisible();
  // What it was asked is its first message; the reviewer's verdict its answer.
  await expect(
    chat.getByText(/^Review the OpenTicker strategy 'SBIN mean reversion'/),
  ).toBeVisible();
  await expect(chat.getByText("keep: net after charges holds up over its runs.")).toBeVisible({
    timeout: 15_000,
  });
  await expect(chat.getByRole("button", { name: /Worked for/ })).toBeVisible();
  await expect(chat.getByText(/^Claude Code · claude-opus-5-5/)).toBeVisible();

  const follow = chat.getByRole("textbox", { name: "Message" });
  await expect(follow).toHaveAttribute("placeholder", "Continue this review as a chat");
  await follow.fill("Why keep it?");
  await follow.press("Enter");
  await expect(chat.getByText(/You asked: Why keep it\? \(resumed [0-9a-f]{8}\)/)).toBeVisible({
    timeout: 15_000,
  });

  const folder = rail.getByRole("button", { name: /^SBIN mean reversion \d+$/ });
  await expect(folder).toHaveAttribute("aria-expanded", "false");
  await folder.click();
  await expect(folder).toHaveAttribute("aria-expanded", "true");
  await expect(
    rail.locator('a[data-child="deep"]', { hasText: "Review of SBIN mean reversion" }).first(),
  ).toBeVisible();
  await expect(rail.getByRole("button", { name: /^Reviews \d+$/ })).toBeVisible();
});

test("a chat with Codex: its effort levels, its events read as steps, and it resumes", async ({
  page,
}) => {
  await signIn(page);
  await page.getByRole("button", { name: "Claude Code" }).click(); // "Use Codex instead"
  await expect(page.getByRole("button", { name: "Codex" })).toBeVisible();

  const picker = page.getByRole("button", { name: /^Model and effort/ });
  await picker.click();
  const menu = page.getByRole("menu", { name: "Model and effort" });
  await expect(menu.getByText("Model · Codex")).toBeVisible();
  // Its own list (`codex debug models`), what its picker shows; any other name is typed.
  await expect(menu.getByRole("menuitemradio", { name: /^GPT-6-Luna/ })).toContainText(
    "Fast and affordable model for easier tasks.",
  );
  await expect(menu.getByRole("menuitemradio", { name: /Codex Auto Review/ })).toHaveCount(0);
  await menu.getByRole("menuitem", { name: "Other model…" }).click();
  await expect(menu.getByRole("textbox", { name: "Model name" })).toBeVisible();
  await expect(menu.getByRole("menuitemradio", { name: "Extra high" })).toHaveCount(0);
  await menu.getByRole("menuitemradio", { name: "Minimal" }).click();
  await page.keyboard.press("Escape");

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Hello Codex");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByText("You asked: Hello Codex", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await expect(chat.getByText("Codex · minimal · 2.6k tokens")).toBeVisible();
  await chat.getByRole("button", { name: /Worked for/ }).click();
  await expect(chat.locator("code", { hasText: "list_strategies" })).toBeVisible();

  const follow = chat.getByRole("textbox", { name: "Message" });
  await follow.fill("And now?");
  await follow.press("Enter");
  await expect(chat.getByText(/You asked: And now\? \(resumed [0-9a-f]{8}\)/)).toBeVisible({
    timeout: 15_000,
  });
  await expect(chat.getByTitle("Fixed after the first message").first()).toContainText("Codex");
});

test("failure: a conversation that's gone says so and starts a new chat with its context", async ({
  page,
}) => {
  await page.goto(nextLink());
  await page.goto("/agents/thr_gone");
  const chat = page.getByRole("region", { name: "Chat" });
  const follow = chat.getByRole("textbox", { name: "Message" });
  await follow.fill("And the worst day?");
  await follow.press("Enter");

  await expect(
    chat
      .getByRole("alert")
      .filter({ hasText: "No conversation found with session ID: gone-1a2b3c4d" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(chat.getByText("its conversation can't be resumed")).toBeVisible();
  await expect(chat.getByRole("status")).toContainText(
    "The agent can't continue this conversation.",
  );
  await expect(follow).toBeDisabled();

  await chat.getByRole("button", { name: "Start a new chat with this context" }).click();
  await expect(page).toHaveURL(/\/agents$/);
  const box = page.getByRole("textbox", { name: "Message" });
  await expect(box).toHaveValue(/^Picking up from the chat "An old chat"\./);
  await expect(box).toHaveValue(/> Tuesday the 6th: ₹4,210 after charges\./);
});

test("failure: a model the agent doesn't know, and a spend cap reached, each say why", async ({
  page,
}) => {
  await signIn(page);
  await page.getByRole("button", { name: /^Model and effort/ }).click();
  const menu = page.getByRole("menu", { name: "Model and effort" });
  await menu.getByRole("menuitem", { name: "Other model…" }).click();
  const name = menu.getByRole("textbox", { name: "Model name" });
  await name.fill("nope-model");
  await name.press("Enter");
  await page.keyboard.press("Escape");
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Which model are you?");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(
    chat.getByRole("alert").filter({ hasText: "issue with the selected model (nope-model)" }),
  ).toBeVisible({ timeout: 15_000 });

  await page.getByRole("link", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "What should we look into?" })).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("Use up the spend cap");
  await page.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(
    chat.getByRole("alert").filter({ hasText: "it reached its spend cap and stopped" }),
  ).toBeVisible({ timeout: 15_000 });
});

test("an answer that lands off its chat: a toast opens it, and its row is unread until seen", async ({
  page,
}) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Tell me later");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/agents\/thr_/);
  await page.keyboard.press("Shift+Meta+O");
  await expect(page).toHaveURL(/\/agents$/);

  const toast = page.getByTestId("toast").filter({ hasText: "Answered in “Tell me later”" });
  await expect(toast).toBeVisible({ timeout: 15_000 });
  const rail = page.getByRole("navigation", { name: "Chats" });
  const row = rail.getByRole("link", { name: /Tell me later/ });
  await expect(row.locator("[data-unread]")).toBeVisible();
  await expect(row).toContainText("now");

  await toast.getByRole("button", { name: "Open" }).click();
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByText("You asked: Tell me later", { exact: true })).toBeVisible();
  await expect(row.locator("[data-unread]")).toHaveCount(0);
});

test("search with ⌘G finds a chat by what was said, and finds an archived one apart", async ({
  page,
}) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Find the gamma squeeze");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByText("You asked: Find the gamma squeeze", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "What should we look into?" })).toBeVisible();

  await page.keyboard.press("Meta+G");
  const search = page.getByRole("dialog", { name: "Search chats" });
  const input = search.getByRole("combobox");
  await input.fill("GAMMA squeeze");
  const hit = search.getByRole("option", { name: /Find the gamma squeeze/ });
  await expect(hit).toContainText("You: Find the gamma squeeze");
  await input.fill("you asked: find the gamma");
  await expect(hit).not.toContainText("You:"); // found in the agent's answer
  await input.press("Enter");
  await expect(search).toHaveCount(0);
  await expect(chat.getByRole("heading", { name: "Find the gamma squeeze" })).toBeVisible();

  const rail = page.getByRole("navigation", { name: "Chats" });
  await rail.getByRole("link", { name: /Find the gamma squeeze/ }).hover();
  await rail.getByRole("button", { name: "Archive Find the gamma squeeze" }).click();
  await rail.getByRole("button", { name: "Search chats" }).click();
  await input.fill("gamma squeeze");
  await expect(search.getByText(/No chat holds “gamma squeeze”/)).toBeVisible();
  await search.getByRole("button", { name: "Archived" }).click();
  await expect(hit).toContainText("Archived");
  await hit.click();

  await expect(chat.getByText("Archived", { exact: true })).toBeVisible();
  await chat.getByRole("button", { name: "Restore" }).click();
  await expect(rail.getByRole("link", { name: /Find the gamma squeeze/ })).toBeVisible();
  await expect(chat.getByRole("button", { name: "Restore" })).toHaveCount(0);
});

test("what changed: a chat's paper order shows under its answer and in the side panel, and cancels", async ({
  page,
}) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Place a paper order for TCS");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(
    chat.getByText("You asked: Place a paper order for TCS", { exact: true }),
  ).toBeVisible({ timeout: 15_000 });

  const card = chat.getByRole("region", { name: "What changed" });
  await expect(card).toContainText("1 change on your desk");
  await expect(card).toContainText("Buy 1 TCS placed");

  await chat.getByRole("button", { name: "Show side panel" }).click();
  const side = page.getByRole("complementary", { name: "Side panel" });
  await expect(side.getByRole("tab", { name: "Changes" })).toHaveAttribute("aria-selected", "true");
  await expect(side).toContainText("Buy 1 TCS placed");
  await expect(side).toContainText("Turns");

  await card.getByRole("button", { name: "Cancel" }).click();
  await expect(card)
    .toContainText("Buy 1 TCS cancelled", { timeout: 10_000 })
    .catch(() => {});
  await expect(card.getByRole("button", { name: "Cancel" })).toHaveCount(0, { timeout: 10_000 });
  await expect(card.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/orders");

  await page.keyboard.press("Alt+Meta+KeyB");
  await expect(side).toHaveCount(0);
});

test("queue a follow-up while the agent works: edit it, take it back, and it runs next", async ({
  page,
}) => {
  await signIn(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Look slowly at the hedges");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/agents\/thr_[0-9a-f]+$/);
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByRole("button", { name: /Working for \d+s/ })).toBeVisible({
    timeout: 15_000,
  });

  // Typing while it works turns Stop into Queue; the message waits under the turn.
  await expect(box).toHaveAttribute("placeholder", "Queue a follow-up");
  await box.fill("And the charges?");
  await expect(chat.getByRole("button", { name: "Queue" })).toBeVisible();
  await box.press("Enter");
  await expect(chat.getByText("Queued. Sends when this turn ends.")).toBeVisible();
  await expect(box).toHaveAttribute("placeholder", /One message waits/);
  await expect(box).toBeDisabled();

  await chat.getByRole("button", { name: "Edit" }).click();
  const edit = chat.getByRole("textbox", { name: "Edit the waiting message" });
  await edit.fill("And the charges, in rupees?");
  await edit.press("Enter");
  await expect(chat.locator(".aw-queued-text")).toHaveText("And the charges, in rupees?");

  await chat.getByRole("button", { name: "Remove" }).click();
  await expect(chat.getByText("Queued. Sends when this turn ends.")).toHaveCount(0);
  await expect(chat.getByText("And the charges, in rupees?")).toHaveCount(0);

  await box.fill("Then sum it up");
  await box.press("Enter");
  await expect(chat.locator(".aw-queued-text")).toHaveText("Then sum it up");
  // Stop ends the turn the agent is on; the waiting message runs next, in the same conversation.
  await chat.getByRole("button", { name: "Stop" }).click();
  await expect(chat.getByText(/You asked: Then sum it up \(resumed/)).toBeVisible({
    timeout: 20_000,
  });
  await expect(chat.getByText("Queued. Sends when this turn ends.")).toHaveCount(0);
  expect(await noOverflow(page)).toEqual([]);
});

test("a read-only chat reads the desk but its paper order is refused, and it stays read-only", async ({
  page,
}) => {
  await signIn(page);
  const orders = () =>
    page.evaluate(() =>
      fetch("/api/v1/orders?broker=fake&limit=200")
        .then((r) => r.json())
        .then((body: { orders: unknown[] }) => body.orders.length),
    );
  const before = await orders();
  await page.getByRole("button", { name: /What the agent may do: Paper trades/ }).click();
  const menu = page.getByRole("menu", { name: "What the agent may do" });
  await expect(menu.getByRole("menuitemradio", { name: /Paper trades/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await menu.getByRole("menuitemradio", { name: /Read only/ }).click();
  await expect(
    page.getByRole("button", { name: "What the agent may do: Read only" }),
  ).toBeVisible();

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Try a paper order for TCS");
  await box.press("Enter");
  const chat = page.getByRole("region", { name: "Chat" });
  await expect(chat.getByText("You asked: Try a paper order for TCS", { exact: true })).toBeVisible(
    { timeout: 15_000 },
  );

  // The key said no: the step shows why, and nothing reached the order book.
  await chat.getByRole("button", { name: /Worked for/ }).click();
  await expect(chat.getByText(/this chat is read-only, so its key changes nothing/)).toBeVisible();
  await expect(chat.getByRole("region", { name: "What changed" })).toHaveCount(0);
  expect(await orders()).toBe(before);
  // Fixed for the chat, like its harness.
  await expect(
    chat.getByTitle("Fixed after the first message").filter({ hasText: "Read only" }),
  ).toBeVisible();
});
