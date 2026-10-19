import { ChevronLeft, ChevronRight } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { spring } from "../lib/motion";

/** What a trading day carries on the calendar: its money and whether something ran. */
export interface DayMark {
  /** The day's net: tints the cell `up` or `down`, deeper for a bigger day. */
  net?: number | null;
  /** A dot under the date: the manager looked, a script ran. */
  dot?: boolean;
  /** Said when the day is pointed at: "+₹1,050.00 · 3 looks". */
  detail?: string;
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

const iso = (d: Date) => d.toISOString().slice(0, 10);
const at = (day: string) => new Date(`${day}T00:00:00Z`);
const addDays = (day: string, n: number) => {
  const d = at(day);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
};

/** "2026-10": the month a day is in. */
export const monthOf = (day: string) => day.slice(0, 7);

/** The month before or after, "2026-10" and -1 is "2026-09". */
export function shiftMonth(month: string, by: number): string {
  const d = at(`${month}-01`);
  d.setUTCMonth(d.getUTCMonth() + by);
  return iso(d).slice(0, 7);
}

/** The first and last day of a month. */
export function monthSpan(month: string): [string, string] {
  const last = at(`${shiftMonth(month, 1)}-01`);
  last.setUTCDate(0);
  return [`${month}-01`, iso(last)];
}

/** The month's weekdays as rows of Mon–Fri; days outside the month are null. */
function weekRows(month: string): (string | null)[][] {
  const [first, last] = monthSpan(month);
  const start = at(first);
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7));
  const rows: (string | null)[][] = [];
  for (let monday = iso(start); monday <= last; monday = addDays(monday, 7)) {
    const row = WEEKDAYS.map((_, i) => {
      const day = addDays(monday, i);
      return monthOf(day) === month ? day : null;
    });
    if (row.some(Boolean)) rows.push(row);
  }
  return rows;
}

const shade = (net: number, scale: number) =>
  Math.min(4, Math.max(1, Math.ceil((Math.abs(net) / scale) * 4)));

/**
 * A trading calendar (DESIGN.md Calendar): the month as Monday-to-Friday
 * rows, because markets don't trade at weekends. Only days in `marks` can be
 * picked (trading days the server knows); a holiday or a day still to come
 * stays in its place, quiet. Each day is tinted by its net and dotted when
 * something ran. Arrow keys walk the days, Page Up / Down the months, Home /
 * End the week; the month slides the way you went.
 */
export function Calendar({
  month,
  onMonth,
  value,
  onPick,
  marks,
  max,
  min,
  today,
  footer,
}: {
  month: string;
  onMonth: (month: string) => void;
  value: string | null;
  onPick: (day: string) => void;
  /** Days that can be picked, with what they carry; undefined while loading. */
  marks: ReadonlyMap<string, DayMark> | undefined;
  max: string;
  min?: string;
  today: string;
  footer?: ReactNode;
}) {
  const rows = weekRows(month);
  const [focus, setFocus] = useState<string | null>(
    value && monthOf(value) === month ? value : null,
  );
  const [hovered, setHovered] = useState<string | null>(null);
  const [direction, setDirection] = useState(0);
  const grid = useRef<HTMLDivElement>(null);
  const scale = Math.max(1, ...[...(marks?.values() ?? [])].map((mark) => Math.abs(mark.net ?? 0)));
  const can = (day: string) => day <= max && (!min || day >= min) && (marks?.has(day) ?? false);
  const canBack = !min || monthSpan(shiftMonth(month, -1))[1] >= min;
  const canOn = shiftMonth(month, 1) <= monthOf(max);

  const go = (by: number) => {
    setDirection(by);
    onMonth(shiftMonth(month, by));
  };

  // The roving focus lands on the chosen day, else the latest that can be picked.
  const days = rows.flat().filter((d): d is string => d !== null);
  const pickable = days.filter(can);
  const tabbable = focus && pickable.includes(focus) ? focus : (pickable.at(-1) ?? null);
  useEffect(() => {
    if (!focus || !grid.current?.contains(document.activeElement)) return;
    grid.current.querySelector<HTMLButtonElement>(`[data-day="${focus}"]`)?.focus();
  }, [focus]);

  const onKey = (event: KeyboardEvent) => {
    const from = tabbable;
    if (!from) return;
    const step: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    if (event.key === "PageUp" || event.key === "PageDown") {
      event.preventDefault();
      go(event.key === "PageUp" ? -1 : 1);
      return;
    }
    const by = step[event.key];
    if (by === undefined) return;
    event.preventDefault();
    // Walk past weekends and days that can't be picked, a few weeks at most.
    let next = from;
    for (let i = 0; i < 40; i++) {
      next = addDays(next, Math.sign(by) * (Math.abs(by) === 7 ? 7 : 1));
      const weekday = at(next).getUTCDay();
      if (weekday === 0 || weekday === 6) continue;
      if (next > max || (min && next < min)) return;
      if (monthOf(next) !== month) {
        setDirection(Math.sign(by));
        onMonth(monthOf(next));
      }
      if (marks?.has(next) || monthOf(next) !== month) {
        setFocus(next);
        return;
      }
    }
  };

  const shown = hovered ?? (value && monthOf(value) === month ? value : null);
  const mark = shown ? marks?.get(shown) : undefined;
  const [y, mo] = month.split("-");

  return (
    <div className="daypick">
      <div className="daypick-head">
        <h3 className="daypick-month" aria-live="polite">
          {MONTHS[Number(mo) - 1]} <span>{y}</span>
        </h3>
        <span className="flex-1" />
        <button
          type="button"
          className="daypick-step"
          aria-label="The month before"
          disabled={!canBack}
          onClick={() => go(-1)}
        >
          <ChevronLeft size={16} aria-hidden />
        </button>
        <button
          type="button"
          className="daypick-step"
          aria-label="The month after"
          disabled={!canOn}
          onClick={() => go(1)}
        >
          <ChevronRight size={16} aria-hidden />
        </button>
      </div>
      <div className="daypick-weekdays" aria-hidden>
        {WEEKDAYS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="daypick-window">
        <AnimatePresence mode="popLayout" initial={false} custom={direction}>
          <m.div
            key={month}
            ref={grid}
            role="group"
            aria-label={`${MONTHS[Number(mo) - 1]} ${y}`}
            className="daypick-days"
            data-loading={marks === undefined || undefined}
            onKeyDown={onKey}
            onMouseLeave={() => setHovered(null)}
            custom={direction}
            variants={{
              enter: (d: number) => ({ opacity: 0, x: d * 24 }),
              still: { opacity: 1, x: 0 },
              leave: (d: number) => ({ opacity: 0, x: d * -24 }),
            }}
            initial="enter"
            animate="still"
            exit="leave"
            transition={spring.snappy}
          >
            {rows.map((row) => (
              <div className="daypick-row" key={row.find(Boolean)}>
                {row.map((day, i) => {
                  if (!day) {
                    // biome-ignore lint/suspicious/noArrayIndexKey: a fixed weekday slot
                    return <span key={i} className="daypick-day" data-out />;
                  }
                  const ok = can(day);
                  const mk = marks?.get(day);
                  const net = mk?.net ?? null;
                  const tone = net == null || net === 0 ? undefined : net > 0 ? "up" : "down";
                  return (
                    <span key={day}>
                      <button
                        type="button"
                        className="daypick-day"
                        data-day={day}
                        data-tone={tone}
                        data-level={net == null || net === 0 ? undefined : shade(net, scale)}
                        data-today={day === today || undefined}
                        data-picked={day === value || undefined}
                        aria-pressed={day === value}
                        disabled={!ok}
                        tabIndex={day === tabbable ? 0 : -1}
                        aria-label={`${day}${mk?.detail ? `, ${mk.detail}` : ""}${ok ? "" : day > max ? ", still to come" : ", no trading"}`}
                        onClick={() => onPick(day)}
                        onFocus={() => setFocus(day)}
                        onMouseEnter={() => setHovered(day)}
                      >
                        {Number(day.slice(8))}
                        {mk?.dot && <i aria-hidden />}
                      </button>
                    </span>
                  );
                })}
              </div>
            ))}
          </m.div>
        </AnimatePresence>
      </div>
      <div className="daypick-readout" aria-live="polite">
        {shown ? (
          <>
            <span>{shown === today ? "Today" : readable(shown)}</span>
            <b data-tone={mark?.net == null ? undefined : mark.net >= 0 ? "up" : "down"}>
              {mark?.detail ?? (marks?.has(shown) ? "" : "No trading")}
            </b>
          </>
        ) : (
          <span>Weekends and holidays are greyed out.</span>
        )}
      </div>
      {footer && <div className="daypick-foot">{footer}</div>}
    </div>
  );
}

const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const SHORT_MONTHS = MONTHS.map((name) => name.slice(0, 3));

/** "Wed 14 Oct". */
function readable(day: string): string {
  const d = at(day);
  return `${SHORT[d.getUTCDay()]} ${d.getUTCDate()} ${SHORT_MONTHS[d.getUTCMonth()]}`;
}
