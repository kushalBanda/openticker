import { type KeyboardEvent, type PointerEvent, useRef } from "react";
import { CLOSE, OPEN, toClock, toMinutes } from "../lib/session";

// The rail runs a little either side of the session, so a start before the
// open or a stop after the close still has somewhere to sit.
const FROM = 9 * 60;
const TO = 16 * 60;
const SNAP = 5;

const pct = (minutes: number) =>
  ((Math.min(TO, Math.max(FROM, minutes)) - FROM) / (TO - FROM)) * 100;

/**
 * When something runs, drawn on the trading day (DESIGN.md Session Window):
 * a rail from 09:00 to 16:00 with the session marked, a start handle and an
 * optional stop handle that drag in 5-minute steps, and the stretch between
 * them filled. Without a stop the fill runs on to the close, dashed: it runs
 * until it exits. Keys work on the handles as on any slider.
 */
export function SessionWindow({
  start,
  stop,
  onStart,
  onStop,
}: {
  start: string;
  stop: string;
  onStart: (value: string) => void;
  onStop: (value: string) => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const s = toMinutes(start);
  const e = stop ? toMinutes(stop) : null;

  const minuteAt = (clientX: number) => {
    const rect = rail.current?.getBoundingClientRect();
    if (!rect) return s;
    const share = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round((FROM + share * (TO - FROM)) / SNAP) * SNAP;
  };

  const drag = (which: "start" | "stop") => (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (clientX: number) => {
      const at = minuteAt(clientX);
      if (which === "start") onStart(toClock(Math.min(at, (e ?? TO + SNAP) - SNAP)));
      else onStop(toClock(Math.max(at, s + SNAP)));
    };
    const target = event.currentTarget;
    const onMove = (ev: globalThis.PointerEvent) => move(ev.clientX);
    const onUp = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
  };

  const keys = (which: "start" | "stop") => (event: KeyboardEvent) => {
    const now = which === "start" ? s : (e ?? CLOSE);
    const step = event.shiftKey ? 15 : SNAP;
    const by =
      event.key === "ArrowRight" || event.key === "ArrowUp"
        ? step
        : event.key === "ArrowLeft" || event.key === "ArrowDown"
          ? -step
          : 0;
    if (!by) return;
    event.preventDefault();
    const next = Math.min(TO, Math.max(FROM, now + by));
    if (which === "start") onStart(toClock(Math.min(next, (e ?? TO + SNAP) - SNAP)));
    else onStop(toClock(Math.max(next, s + SNAP)));
  };

  // A click on the rail moves the nearer handle there; with no stop, it sets one.
  const onRail = (event: PointerEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const at = minuteAt(event.clientX);
    if (e === null ? at < s : Math.abs(at - s) <= Math.abs(at - e)) {
      onStart(toClock(Math.min(at, (e ?? TO + SNAP) - SNAP)));
    } else {
      onStop(toClock(Math.max(at, s + SNAP)));
    }
  };

  const fillTo = e ?? Math.max(CLOSE, s);
  const runs = e === null ? "until it exits" : `${Math.round((e - s) / 6) / 10} h`;

  return (
    <div className="session-window">
      <div ref={rail} className="session-rail" onPointerDown={onRail}>
        <span
          className="session-market"
          style={{ left: `${pct(OPEN)}%`, width: `${pct(CLOSE) - pct(OPEN)}%` }}
          aria-hidden
        />
        <span
          className="session-run"
          data-open-ended={e === null || undefined}
          style={{ left: `${pct(s)}%`, width: `${Math.max(0, pct(fillTo) - pct(s))}%` }}
          aria-hidden
        />
        <button
          type="button"
          role="slider"
          className="session-handle"
          style={{ left: `${pct(s)}%` }}
          aria-label="Start on the session"
          aria-valuemin={FROM}
          aria-valuemax={TO}
          aria-valuenow={s}
          aria-valuetext={start}
          onPointerDown={drag("start")}
          onKeyDown={keys("start")}
        />
        {e !== null && (
          <button
            type="button"
            role="slider"
            className="session-handle"
            data-stop
            style={{ left: `${pct(e)}%` }}
            aria-label="Stop on the session"
            aria-valuemin={FROM}
            aria-valuemax={TO}
            aria-valuenow={e}
            aria-valuetext={stop}
            onPointerDown={drag("stop")}
            onKeyDown={keys("stop")}
          />
        )}
      </div>
      <div className="session-scale" aria-hidden>
        <span style={{ left: `${pct(OPEN)}%` }}>09:15 open</span>
        <span style={{ left: `${pct(12 * 60)}%` }}>12:00</span>
        <span style={{ left: `${pct(CLOSE)}%` }}>15:30 close</span>
      </div>
      <p className="note session-says">
        Runs {start}
        {e === null ? "" : `–${stop}`} IST, {runs}
        {s < OPEN ? ", from before the open" : ""}
        {e !== null && e > CLOSE ? ", past the close" : ""}.
        {e === null && " Click the rail after the start to give it a stop."}
      </p>
    </div>
  );
}
