import { readFileSync, writeFileSync } from "node:fs";

// The server writes one-time sign-in links; each test takes the next. The
// count is kept in a file: Playwright starts a new worker after a failure.
const dir = "test-results/e2e-home";

export function nextLink(): string {
  const links = readFileSync(`${dir}/links.txt`, "utf8").trim().split("\n");
  let used = 0;
  try {
    used = Number(readFileSync(`${dir}/used.txt`, "utf8"));
  } catch {
    // the first test
  }
  writeFileSync(`${dir}/used.txt`, String(used + 1));
  const link = links[used];
  if (!link) throw new Error("out of sign-in links: raise the count in e2e_server.py");
  return link;
}
