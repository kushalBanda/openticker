import { useEffect } from "react";
import type { Side } from "../lib/orders";
import { typing } from "./Sidebar";

/** B and S open the order window, as in Kite; not after "g" (that's for pages). */
export function useSideKeys(open: (side: Side) => void) {
  useEffect(() => {
    let armed = 0;
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      if (event.key === "g") {
        armed = event.timeStamp;
        return;
      }
      const afterG = armed && event.timeStamp - armed < 1000;
      armed = 0;
      if (afterG) return;
      if (event.key === "b" || event.key === "s") {
        event.preventDefault();
        open(event.key === "b" ? "BUY" : "SELL");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
}
