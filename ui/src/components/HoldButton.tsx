import { type AnimationPlaybackControls, animate, useMotionValue } from "motion/react";
import * as m from "motion/react-m";
import { useRef, useState } from "react";
import { duration } from "../lib/motion";

/**
 * For what one click must not do (DESIGN.md Hold Button): the fill grows
 * over `durationMs`; letting go early resets it and does nothing. Space and
 * Enter hold the same way.
 */
export function HoldButton({
  label,
  onConfirm,
  durationMs = 1200,
  disabled,
  size,
}: {
  label: string;
  onConfirm: () => Promise<void>;
  durationMs?: number;
  disabled?: boolean;
  size?: "sm";
}) {
  const progress = useMotionValue(0);
  const running = useRef<AnimationPlaybackControls | null>(null);
  const [busy, setBusy] = useState(false);

  const start = () => {
    if (busy || disabled || running.current) return;
    running.current = animate(progress, 1, {
      duration: durationMs / 1000,
      ease: "linear",
      onComplete: () => {
        running.current = null;
        setBusy(true);
        onConfirm().finally(() => {
          setBusy(false);
          progress.set(0);
        });
      },
    });
  };
  const release = () => {
    if (!running.current) return;
    running.current.stop();
    running.current = null;
    animate(progress, 0, { duration: duration.fast });
  };

  return (
    <button
      type="button"
      className="btn hold"
      data-size={size}
      disabled={disabled || busy}
      aria-label={`${label} (press and hold)`}
      onPointerDown={start}
      onPointerUp={release}
      onPointerLeave={release}
      onPointerCancel={release}
      onKeyDown={(event) => {
        if ((event.key === " " || event.key === "Enter") && !event.repeat) {
          event.preventDefault();
          start();
        }
      }}
      onKeyUp={(event) => {
        if (event.key === " " || event.key === "Enter") release();
      }}
    >
      <m.span className="hold-fill" style={{ scaleX: progress }} aria-hidden />
      <span>{busy ? "Working…" : label}</span>
    </button>
  );
}
