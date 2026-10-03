import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { ApiError, shouldRetry } from "../../src/api/client";
import { loaded, StatCard } from "../../src/components/StatCard";
import { failureOf, TableFailed } from "../../src/components/TableStates";
import { brokerName } from "../../src/lib/format";
import { type FeedStatus, sessionExpired } from "../../src/stream/connection";

const query = (over: Partial<Parameters<typeof failureOf>[0]> = {}) => ({
  data: undefined,
  isError: false,
  error: null,
  refetch: vi.fn(),
  ...over,
});

describe("what a page shows while loading, and once something failed", () => {
  test("a stat is a skeleton while loading, — once failed, the figure when there", () => {
    const show = (value: ReturnType<typeof loaded>) =>
      render(<StatCard label="Funds" value={value} />).container;
    expect(show(loaded(query(), () => "x")).querySelector(".skeleton")).not.toBeNull();
    expect(show(loaded(query({ isError: true }), () => "x")).textContent).toContain("—");
    expect(show(loaded(query({ data: 5 }), (n) => `n=${n}`)).textContent).toContain("n=5");
  });

  test("an old figure stays when a refetch fails", () => {
    const failed = query({ data: 5, isError: true, error: new Error("down") });
    expect(failureOf(failed)).toBeUndefined();
  });

  test("a failed tile says what, why, and asks again", async () => {
    const refetch = vi.fn();
    const failure = failureOf(query({ isError: true, error: new Error("Server down."), refetch }));
    if (!failure) throw new Error("expected a failure");
    render(<TableFailed what="Positions" failure={failure} />);
    expect(screen.getByRole("alert").textContent).toContain("Positions didn't load: Server down.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  test("refusals aren't asked again; faults are, twice", () => {
    expect(shouldRetry(0, new ApiError(404, "no strategy"))).toBe(false);
    expect(shouldRetry(0, new ApiError(403, "not allowed"))).toBe(false);
    expect(shouldRetry(0, new ApiError(503, "down"))).toBe(true);
    expect(shouldRetry(1, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, "down"))).toBe(false);
  });
});

describe("the broker", () => {
  const status = (over: Partial<FeedStatus>): FeedStatus => ({
    broker: "zerodha",
    broker_connected: false,
    broker_expires_at: null,
    last_tick_at: null,
    market_open: true,
    state: "no-broker",
    ...over,
  });
  const now = new Date("2026-09-22T05:00:00Z");

  test("expired only when a session there was has run out", () => {
    expect(sessionExpired(status({ broker_expires_at: "2026-09-22T00:30:00Z" }), now)).toBe(true);
    expect(sessionExpired(status({}), now)).toBe(false); // never logged in
    expect(
      sessionExpired(
        status({ broker_connected: true, broker_expires_at: "2026-09-22T00:30:00Z" }),
        now,
      ),
    ).toBe(false);
  });

  test("is named as people know it", () => {
    expect(brokerName("zerodha")).toBe("Zerodha");
    expect(brokerName("fake")).toBe("Fake");
  });
});
