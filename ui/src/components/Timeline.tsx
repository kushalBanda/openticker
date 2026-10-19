import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useEffect, useRef } from "react";
import { spring } from "../lib/motion";

export type Tone = "up" | "down" | "accent" | "warn";

export interface TimelineEntry {
  key: string;
  /** When, as the row shows it: "10:31". */
  time: ReactNode;
  /** The instant, for <time dateTime>. */
  at?: Date;
  /** The dot's colour: what kind of thing happened. Muted by default. */
  tone?: Tone;
  /** Still happening: the dot rings. */
  live?: boolean;
  body: ReactNode;
}

/**
 * Things in the order they happened (DESIGN.md Timeline): the time, a dot on
 * one hairline rail, then what happened. Newest first by convention; an entry
 * that arrives while the list is on screen slides in at the top. `dense` is
 * one line an entry, 44px, for a tile's short list.
 */
export function Timeline({
  entries,
  label,
  dense,
  className,
}: {
  entries: TimelineEntry[];
  label: string;
  dense?: boolean;
  className?: string;
}) {
  // Entries there on first paint are simply there; only later ones arrive.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
  }, []);
  return (
    <ol
      className={className ? `timeline ${className}` : "timeline"}
      data-dense={dense || undefined}
      aria-label={label}
    >
      <AnimatePresence initial={false}>
        {entries.map((entry) => (
          <m.li
            key={entry.key}
            layout={mounted.current ? "position" : false}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={spring.soft}
          >
            <time
              className="timeline-time"
              dateTime={entry.at ? entry.at.toISOString() : undefined}
            >
              {entry.time}
            </time>
            <span
              className="timeline-dot"
              data-tone={entry.tone}
              data-live={entry.live || undefined}
              aria-hidden
            />
            <div className="timeline-body">{entry.body}</div>
          </m.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}
