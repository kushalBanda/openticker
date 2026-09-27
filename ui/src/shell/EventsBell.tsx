import { Bell } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { byLabel, describe } from "../lib/events";
import { istClock, istDate } from "../lib/format";
import { enter, leave } from "../lib/motion";
import { useServerNow } from "../stream/StreamProvider";
import { useEvents } from "./events";

const SHOWN = 20;

/** The status bar's bell: unread count, and the latest events in a popover. */
export function EventsBell() {
  const { entries, unread, markAllRead, names } = useEvents();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const serverNow = useServerNow();

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !box.current?.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  const today = istDate(serverNow());
  const label = unread ? `Events, ${unread} unread` : "Events";

  return (
    <span className="relative" ref={box}>
      <button
        type="button"
        className="bar-button"
        aria-label={label}
        title={label}
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        <Bell aria-hidden />
        {unread > 0 && (
          <span className="bell-count" data-testid="bell-count">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      <AnimatePresence>
        {open && (
          <m.div className="menu bell" role="dialog" aria-label="Events" {...enter} exit={leave}>
            <div className="bell-head">
              <b>Events</b>
              <span className="flex-1" />
              <button
                type="button"
                className="btn"
                data-variant="ghost"
                data-size="sm"
                disabled={unread === 0}
                onClick={markAllRead}
              >
                Mark all read
              </button>
            </div>
            {entries === undefined ? (
              <div className="menu-note">Loading…</div>
            ) : entries.length === 0 ? (
              <div className="menu-note">Nothing yet. Fills, stops and reviews show up here.</div>
            ) : (
              <ul className="bell-list">
                {entries.slice(0, SHOWN).map((entry) => {
                  const said = describe(entry, names);
                  const at = new Date(entry.occurred_at);
                  const when = istDate(at) === today ? istClock(at) : istDate(at, { time: true });
                  return (
                    <li key={entry.id}>
                      <span className="badge" data-tone={said.tone}>
                        {said.kind}
                      </span>{" "}
                      {said.text}
                      <div className="note">
                        {when} · {byLabel(entry, names)}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            <Link to="/activity" className="bell-more" onClick={() => setOpen(false)}>
              All activity
            </Link>
          </m.div>
        )}
      </AnimatePresence>
    </span>
  );
}
