import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { duration, ease, spring } from "../lib/motion";

/**
 * A modal over the scrim (DESIGN.md Elevation: Modal). Escape and a click on
 * the scrim close it; focus moves in on open and back to where it was on close.
 */
export function Dialog({
  open,
  onClose,
  title,
  aside,
  children,
  width = 440,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  width?: number;
}) {
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>(
      "input:checked, input, button:not([disabled])",
    );
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      before?.focus();
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          className="scrim"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: duration.fast } }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <m.div
            ref={box}
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            style={{ width }}
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: spring.soft }}
            exit={{
              opacity: 0,
              scale: 0.98,
              transition: { duration: duration.fast, ease: ease.in },
            }}
          >
            <div className="flex items-center gap-3">
              <h2 id={titleId}>{title}</h2>
              <span className="flex-1" />
              {aside}
            </div>
            {children}
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
