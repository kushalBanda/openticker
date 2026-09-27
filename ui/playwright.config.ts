import { defineConfig } from "@playwright/test";

// End to end against openticker-serve's app with the fake broker and a walking
// live feed (tests/fixtures/e2e_server.py). Build first: `pnpm build`.
const port = 8751;
const home = "test-results/e2e-home";

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1, // one server, one pool of sign-in links
  use: { baseURL: `http://127.0.0.1:${port}` },
  // Placing the iron fly and events change the account (Claude's TCS), so
  // they run after the rest;
  // the Dashboard's visit needs events of its own; Settings logs the broker
  // out and wipes the account, so it runs before Scripts + Agents, which
  // start and stop a real hosted script and a review job undisturbed by that.
  projects: [
    {
      name: "app",
      testIgnore: /(options|events|dashboard|settings|scripts|agents)\.spec\.ts/,
    },
    { name: "options", testMatch: /options\.spec\.ts/, dependencies: ["app"] },
    { name: "events", testMatch: /events\.spec\.ts/, dependencies: ["options"] },
    { name: "dashboard", testMatch: /dashboard\.spec\.ts/, dependencies: ["events"] },
    { name: "settings", testMatch: /settings\.spec\.ts/, dependencies: ["dashboard"] },
    {
      name: "scripts-and-agents",
      testMatch: /(scripts|agents)\.spec\.ts/,
      dependencies: ["settings"],
    },
  ],
  webServer: {
    command: `rm -rf ${home} && mkdir -p ${home} && cd .. && uv run python -m tests.fixtures.e2e_server --port ${port} --home ui/${home} --links ui/${home}/links.txt`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
