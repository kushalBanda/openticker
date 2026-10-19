import { type KeyboardEvent, useId, useRef, useState } from "react";

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * A 24-hour time, IST, as two parts you type into or nudge (DESIGN.md Time
 * Field): digits fill the hour then move to the minutes, ↑ / ↓ step (Shift
 * for 5 minutes or 1 hour), Backspace empties the field when it may be empty.
 * The value is "HH:MM", or "" when `optional` and left empty.
 */
export function TimeField({
  label,
  value,
  onChange,
  optional,
  invalid,
  seed = "09:15",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  optional?: boolean;
  invalid?: boolean;
  /** Where an empty field starts when a part is nudged or typed: "15:30" for a stop. */
  seed?: string;
}) {
  const id = useId();
  const minutes = useRef<HTMLSpanElement>(null);
  const hours = useRef<HTMLSpanElement>(null);
  // Digits typed into a part so far, until the part is full.
  const [typed, setTyped] = useState<{ part: "h" | "m"; digits: string } | null>(null);
  const [h, m] = value ? value.split(":").map(Number) : [null, null];
  const [seedH = 9, seedM = 0] = seed.split(":").map(Number);

  const set = (hour: number | null, minute: number | null) =>
    onChange(`${pad(hour ?? seedH)}:${pad(minute ?? seedM)}`);

  const onKey = (part: "h" | "m") => (event: KeyboardEvent) => {
    const max = part === "h" ? 23 : 59;
    const now = part === "h" ? h : m;
    const big = event.shiftKey ? (part === "h" ? 1 : 5) : 1;
    const write = (n: number) => (part === "h" ? set(n, m) : set(h, n));
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      const by = event.key === "ArrowUp" ? big : -big;
      const start = now ?? (part === "h" ? seedH : seedM);
      write((((start + by) % (max + 1)) + max + 1) % (max + 1));
      setTyped(null);
      return;
    }
    if (/^\d$/.test(event.key)) {
      event.preventDefault();
      const digits = (typed?.part === part ? typed.digits : "") + event.key;
      const n = Number(digits);
      if (n > max) {
        // A first digit too big for two: it is the whole part.
        write(Number(event.key));
        setTyped({ part, digits: event.key });
        return;
      }
      write(n);
      // Two digits, or one that can't start a second: the part is done.
      const full = digits.length === 2 || n * 10 > max;
      setTyped(full ? null : { part, digits });
      if (full && part === "h") minutes.current?.focus();
      return;
    }
    if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault();
      setTyped(null);
      if (optional) onChange("");
      else write(0);
      return;
    }
    if (event.key === ":" && part === "h") {
      event.preventDefault();
      minutes.current?.focus();
    }
    if (event.key === "ArrowRight" && part === "h") minutes.current?.focus();
    if (event.key === "ArrowLeft" && part === "m") hours.current?.focus();
  };

  const part = (which: "h" | "m") => {
    const n = which === "h" ? h : m;
    return (
      <span
        ref={which === "h" ? hours : minutes}
        role="spinbutton"
        tabIndex={0}
        className="time-part"
        aria-label={which === "h" ? "Hour" : "Minute"}
        aria-valuemin={0}
        aria-valuemax={which === "h" ? 23 : 59}
        aria-valuenow={n ?? undefined}
        aria-valuetext={n === null ? "empty" : pad(n)}
        data-empty={n === null || undefined}
        onKeyDown={onKey(which)}
        onBlur={() => setTyped(null)}
      >
        {n === null ? "--" : pad(n)}
      </span>
    );
  };

  return (
    <div className="field">
      <span className="label" id={`${id}-label`}>
        {label}
      </span>
      {/* biome-ignore lint/a11y/useSemanticElements: a group of two spinbuttons, as a native time input is */}
      <div
        className="input time-field"
        role="group"
        aria-labelledby={`${id}-label`}
        aria-invalid={invalid || undefined}
        data-value={value}
        onPointerDown={(event) => {
          // A click on the box, not a part, starts at the hour.
          if (event.target === event.currentTarget) {
            event.preventDefault();
            hours.current?.focus();
          }
        }}
      >
        {part("h")}
        <span className="time-colon" aria-hidden>
          :
        </span>
        {part("m")}
        <span className="time-zone" aria-hidden>
          IST
        </span>
      </div>
    </div>
  );
}
