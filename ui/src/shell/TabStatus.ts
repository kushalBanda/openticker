import { useEffect, useRef, useState } from "react";
import { useToday } from "../api/queries";
import { tabTitle } from "../lib/today";
import { useLive } from "../stream/StreamProvider";
import { useEvents } from "./events";
import { useBarTitle } from "./title";

const EVERY_MS = 5_000; // the tab changes at most this often (DESIGN.md Browser Tab)

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

/** The tab's title: today's P&L after charges, then the page ("+₹6,976 · Positions"). */
function useTabTitle(): void {
  const { status } = useLive();
  const net = useToday(status?.broker).data?.net_pnl;
  const { title } = useBarTitle();
  const [shown, setShown] = useState<number | null | undefined>(net);
  const last = useRef(0);

  useEffect(() => {
    const wait = Math.max(0, last.current + EVERY_MS - Date.now());
    const timer = setTimeout(() => {
      last.current = Date.now();
      setShown(net);
    }, wait);
    return () => clearTimeout(timer);
  }, [net]);

  useEffect(() => {
    if (title) document.title = tabTitle(shown, title);
  }, [shown, title]);
}

/** Keeps the favicon's dot in step with unread must-act events, and the title with today. */
export function useTabStatus(): void {
  useTabTitle();
  const { urgent } = useEvents();
  const dot = urgent.length > 0;
  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;
    link.href = dot ? icon(true) : "/favicon.svg";
    link.dataset.dot = dot ? "true" : "false";
  }, [dot]);
}
