import { act, renderHook } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { chooseTheme, useTheme, useThemeChoice } from "../../src/lib/theme";

vi.stubGlobal("matchMedia", (query: string) => ({
  matches: false, // the system is light
  media: query,
  addEventListener: () => {},
  removeEventListener: () => {},
}));

test("every reader follows one choice, and system forgets it", () => {
  const choice = renderHook(() => useThemeChoice());
  const theme = renderHook(() => useTheme());

  act(() => chooseTheme("dark"));
  expect(choice.result.current[0]).toBe("dark");
  expect(theme.result.current[0]).toBe("dark");
  expect(localStorage.getItem("ot-theme")).toBe("dark");

  act(() => chooseTheme("system"));
  expect(choice.result.current[0]).toBe("system");
  expect(theme.result.current[0]).toBe("light");
  expect(localStorage.getItem("ot-theme")).toBeNull();
});
