import { useSyncExternalStore } from "react";

// The theme follows the system until the user picks one, which this machine
// remembers (DESIGN.md). index.html applies it before first paint. One store,
// so the status bar's toggle and Settings always agree.

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";

const KEY = "ot-theme";
const query = "(prefers-color-scheme: dark)";

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function system(): Theme {
  return window.matchMedia(query).matches ? "dark" : "light";
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/** Switches with one cross-fade where the browser can, else at once. */
function switchTo(theme: Theme) {
  if (document.documentElement.dataset.theme === theme) return;
  if (typeof document.startViewTransition === "function") {
    document.startViewTransition(() => apply(theme));
  } else {
    apply(theme);
  }
}

const listeners = new Set<() => void>();
let choice: ThemeChoice = typeof window === "undefined" ? "system" : (stored() ?? "system");

function notify() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  if (listeners.size === 0) window.matchMedia(query).addEventListener("change", follow);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.matchMedia(query).removeEventListener("change", follow);
  };
}

function follow() {
  if (choice !== "system") return;
  switchTo(system());
  notify();
}

export function chooseTheme(next: ThemeChoice) {
  try {
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    // private window: the choice lasts this page only
  }
  choice = next;
  switchTo(next === "system" ? system() : next);
  notify();
}

/** What the user picked: light, dark, or following the system. */
export function useThemeChoice(): [ThemeChoice, (next: ThemeChoice) => void] {
  const current = useSyncExternalStore(subscribe, () => choice);
  return [current, chooseTheme];
}

/** The theme on screen now, and a way to pick one. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const current = useSyncExternalStore(subscribe, () => (choice === "system" ? system() : choice));
  return [current, chooseTheme];
}
