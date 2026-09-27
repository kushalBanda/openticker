import { useSyncExternalStore } from "react";

// Desktop notifications: off until the user turns them on in Settings, and
// then only for must-act events while this tab is hidden (DESIGN.md). The
// choice is this browser's.

const KEY = "ot.notify.desktop";
const listeners = new Set<() => void>();

export const desktopSupported = () => typeof Notification !== "undefined";

function read(): boolean {
  try {
    return (
      desktopSupported() &&
      Notification.permission === "granted" &&
      localStorage.getItem(KEY) === "on"
    );
  } catch {
    return false;
  }
}

let on = typeof window === "undefined" ? false : read();

function set(next: boolean) {
  try {
    if (next) localStorage.setItem(KEY, "on");
    else localStorage.removeItem(KEY);
  } catch {
    // private window: lasts this page only
  }
  on = next;
  for (const listener of listeners) listener();
}

/** Asks the browser once; false when the user or the browser says no. */
export async function turnDesktopOn(): Promise<boolean> {
  if (!desktopSupported()) return false;
  const permission =
    Notification.permission === "default"
      ? await Notification.requestPermission()
      : Notification.permission;
  set(permission === "granted");
  return permission === "granted";
}

export function turnDesktopOff() {
  set(false);
}

export function useDesktopNotifications(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => on,
  );
}

/** Shows one when they're on and nobody is looking at this tab. */
export function notifyDesktop(title: string, body: string, onClick: () => void) {
  if (!on || !document.hidden || !desktopSupported()) return;
  const shown = new Notification(title, { body, tag: title });
  shown.onclick = () => {
    window.focus();
    onClick();
    shown.close();
  };
}
