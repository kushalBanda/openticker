import { useEffect, useState } from "react";

// The theme follows the system until the user picks one, which this machine
// remembers (DESIGN.md). index.html applies it before first paint.

export type Theme = "light" | "dark";

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

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => stored() ?? system());

  useEffect(() => {
    const media = window.matchMedia(query);
    const follow = () => {
      if (stored() === null) {
        setThemeState(system());
        switchTo(system());
      }
    };
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);

  const choose = (next: Theme) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // private window: the choice lasts this page only
    }
    setThemeState(next);
    switchTo(next);
  };
  return [theme, choose];
}
