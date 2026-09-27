import { useAnimate, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { MISSING, price } from "../lib/format";
import { duration, ease } from "../lib/motion";
import type { Tick } from "../stream/connection";
import { useIsStale } from "../stream/prices";

/**
 * A last price in a table, flashing up-soft or down-soft on a change
 * (DESIGN.md), with Stale after a quiet minute while `watching`.
 */
export function LivePrice({
  value,
  tick,
  watching,
}: {
  value: number | null;
  tick: Tick | undefined;
  watching: boolean;
}) {
  const [scope, animate] = useAnimate<HTMLSpanElement>();
  const reduced = useReducedMotion();
  const before = useRef(value);
  const stale = useIsStale(tick, watching);

  useEffect(() => {
    const was = before.current;
    before.current = value;
    if (reduced || was === null || value === null || was === value || !scope.current) return;
    const soft = getComputedStyle(document.documentElement)
      .getPropertyValue(value > was ? "--up-soft" : "--down-soft")
      .trim();
    animate(
      scope.current,
      { backgroundColor: [soft, "rgba(0, 0, 0, 0)"] },
      { duration: duration.slow, ease: ease.out },
    );
  }, [value, reduced, animate, scope]);

  return (
    <span className="inline-flex items-center justify-end gap-2">
      {stale && (
        <span className="badge" data-tone="warn">
          Stale
        </span>
      )}
      <span ref={scope} className="rounded-sm px-1" data-testid="ltp">
        {value === null ? <span className="missing">{MISSING}</span> : price(value)}
      </span>
    </span>
  );
}
