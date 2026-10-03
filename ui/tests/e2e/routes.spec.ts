import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { nextLink } from "./links";

// Every route the app has, checked the same way (DESIGN.md, the launch bar):
// nothing scrolls sideways at 1280 / 1440 / 1920 in either theme, axe finds no
// contrast or other WCAG A/AA fault in either theme, and with reduced motion
// nothing moves. Each page's own spec proves what it does; this proves none
// of them was left out.

const STATIC = [
  "/",
  "/watchlist",
  "/options",
  "/positions",
  "/orders",
  "/trades",
  "/strategies",
  "/scripts",
  "/agents",
  "/activity",
  "/settings",
  "/symbols/NSE/RELIANCE",
  "/symbols/NFO/NIFTY29SEP2624800PE",
  "/nowhere",
];

/** Every route, the detail pages opened on the seeded strategy and script. */
async function routes(page: Page): Promise<string[]> {
  const strategies = await (await page.request.get("/api/v1/strategies")).json();
  const scripts = await (await page.request.get("/api/v1/scripts")).json();
  const details = [
    ...strategies.strategies.map((s: { strategy_id: string }) => `/strategies/${s.strategy_id}`),
    ...scripts.scripts.map((s: { script_id: string }) => `/scripts/${s.script_id}`),
  ];
  expect(details.length).toBeGreaterThan(0);
  return [...STATIC, ...details];
}

/** Opens a route and waits until its data has replaced the skeletons. */
async function open(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 5_000 });
}

const setTheme = (page: Page, theme: "light" | "dark") =>
  page.evaluate((t) => {
    document.documentElement.dataset.theme = t;
  }, theme);

const overflowing = (page: Page) =>
  page.evaluate(() =>
    [document.documentElement, ...document.querySelectorAll(".tile, .toolbar, .statusbar, main")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.className || el.tagName),
  );

for (const width of [1280, 1440, 1920]) {
  test(`every route at ${width}px, light and dark: no sideways scroll`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(nextLink());
    for (const path of await routes(page)) {
      await open(page, path);
      for (const theme of ["light", "dark"] as const) {
        await setTheme(page, theme);
        await page.waitForTimeout(250); // the theme's colour transition
        expect.soft({ path, theme, overflow: await overflowing(page) }).toEqual({
          path,
          theme,
          overflow: [],
        });
      }
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`every route passes axe in ${theme}`, async ({ page }) => {
    test.setTimeout(180_000);
    // No price flash or reveal mid-check: axe reads colours as they stand.
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(nextLink());
    const check = async (where: string) => {
      // Colours as they settle: axe reads a colour mid-transition as it
      // stands (a highlighted row fading in blends its text and ground).
      await page.waitForFunction(() =>
        document.getAnimations().every((a) => a.playState !== "running"),
      );
      await page.waitForTimeout(100);
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const found = violations.map((v) => ({
        rule: v.id,
        nodes: v.nodes.slice(0, 3).map((n) => `${n.target.join(" ")}: ${n.failureSummary}`),
      }));
      expect.soft({ where, found }).toEqual({ where, found: [] });
    };
    for (const path of await routes(page)) {
      await open(page, path);
      await setTheme(page, theme);
      await check(path);
    }

    // What opens over a page: the order window, the palette, the bell.
    await open(page, "/symbols/NSE/RELIANCE");
    await page.keyboard.press("b");
    await expect(page.getByRole("dialog", { name: /Buy RELIANCE/ })).toBeVisible();
    await check("order window");
    await page.keyboard.press("Escape");
    await page.keyboard.press("ControlOrMeta+k");
    await page.keyboard.type("RELI");
    await expect(page.getByRole("dialog", { name: "Search" })).toBeVisible();
    await check("palette");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /^Events/ }).click();
    await expect(page.getByRole("dialog", { name: "Events" })).toBeVisible();
    await check("bell");
  });
}

test("with reduced motion, nothing on any route moves", async ({ page }) => {
  test.setTimeout(120_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(nextLink());
  for (const path of await routes(page)) {
    await open(page, path);
    await page.mouse.wheel(0, 600); // the hero tuck and the title into the bar
    await page.waitForTimeout(300);
    // Running animations may fade (opacity) or tint; nothing may travel,
    // scale, wipe or pulse.
    const moving = await page.evaluate(() => {
      const still = new Set([
        "offset",
        "computedOffset",
        "easing",
        "composite",
        "opacity",
        "color",
        "backgroundColor",
        "borderColor",
        "fill",
        "stroke",
      ]);
      return document
        .getAnimations()
        .filter((a) => a.playState === "running")
        .flatMap((a) => {
          const effect = a.effect as KeyframeEffect | null;
          const props = (effect?.getKeyframes() ?? []).flatMap((k) => Object.keys(k));
          const moves = [...new Set(props.filter((p) => !still.has(p)))];
          const el = effect?.target as Element | null;
          const name = (a as CSSAnimation).animationName ?? a.constructor.name;
          return moves.length ? [`${el?.className || el?.tagName} ${name}: ${moves}`] : [];
        });
    });
    expect.soft({ path, moving }).toEqual({ path, moving: [] });
  }
});

test("the theme chosen stays through every page and a reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto(nextLink());
  const html = page.locator("html");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  for (const path of ["/positions", "/strategies", "/settings", "/symbols/NSE/RELIANCE"]) {
    await open(page, path);
    await expect(html).toHaveAttribute("data-theme", "dark");
  }
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
});
