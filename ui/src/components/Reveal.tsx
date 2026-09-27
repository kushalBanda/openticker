import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { spring } from "../lib/motion";

/**
 * Reveal once (DESIGN.md Scroll effects): below the first screen, the tile
 * fades up 8px the first time it comes into view, then never again. In the
 * first screen, and under reduced motion, it is simply there.
 */
export function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const [below, setBelow] = useState(false);

  useLayoutEffect(() => {
    const element = box.current;
    if (element && element.getBoundingClientRect().top > window.innerHeight) setBelow(true);
  }, []);

  if (reduced || !below) {
    return (
      <div ref={box} className={className}>
        {children}
      </div>
    );
  }
  return (
    <m.div
      ref={box}
      className={className}
      initial={{ opacity: 0, y: 8 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={spring.soft}
    >
      {children}
    </m.div>
  );
}
