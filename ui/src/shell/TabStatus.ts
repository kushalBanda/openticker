import { useEffect } from "react";
import { useEvents } from "./events";

// The app's mark, with a red dot when an unread event needs the user
// (decision 17): seen from another tab without opening this one.
const MARK =
  '<rect x="15" y="1" width="2" height="30" rx="1" fill="#ffcc00"/>' +
  '<rect x="12" y="5" width="8" height="22" rx="1.5" fill="#ffcc00"/>';
const DOT = '<circle cx="25" cy="7" r="6" fill="#e5484d" stroke="#fff" stroke-width="2"/>';
const icon = (dot: boolean) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${MARK}${dot ? DOT : ""}</svg>`,
  )}`;

/** Keeps the favicon's dot in step with unread must-act events. The title is the page's own. */
export function useTabStatus(): void {
  const { urgent } = useEvents();
  const dot = urgent.length > 0;
  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;
    link.href = dot ? icon(true) : "/favicon.svg";
    link.dataset.dot = dot ? "true" : "false";
  }, [dot]);
}
