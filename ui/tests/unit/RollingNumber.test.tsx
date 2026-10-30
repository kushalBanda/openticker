import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { RollingNumber } from "../../src/components/RollingNumber";

function setVisibility(state: DocumentVisibilityState) {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

afterEach(() => vi.restoreAllMocks());

describe("RollingNumber", () => {
  test("is drawn afresh when the tab is shown again, not when it is hidden", () => {
    const { container } = render(<RollingNumber value={49559.34} locales="en-IN" />);
    const first = container.firstElementChild;
    expect(first).not.toBeNull();

    setVisibility("hidden");
    expect(container.firstElementChild).toBe(first);

    setVisibility("visible");
    expect(container.firstElementChild).not.toBe(first);
  });
});
