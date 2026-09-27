import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { duration, ease, spring } from "../lib/motion";

/**
 * A modal over the scrim (DESIGN.md Elevation: Modal). Escape and a click on
 * the scrim close it; focus moves in on open and back to where it was on close.
 * With a `tone`, the head is tinted for the side (the order window) and the
 * children are its body and foot, edge to edge.
 */
export function Dialog({
  open,
  onClose,
  title,
  aside,
  head,
  tone,
  children,
  width = 440,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  aside?: ReactNode;
  /** A line under the title, inside the tinted head. */
  head?: ReactNode;
  tone?: "up" | "down";
  children: ReactNode;
  width?: number;
}) {
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>(
      "[data-autofocus], input:checked, input, button:not([disabled])",
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
            data-flush={tone !== undefined}
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: spring.soft }}
            exit={{
              opacity: 0,
              scale: 0.98,
              transition: { duration: duration.fast, ease: ease.in },
            }}
          >
            <div className="dialog-head" data-tone={tone}>
              <div className="flex items-center gap-3">
                <h2 id={titleId}>{title}</h2>
                <span className="flex-1" />
                {aside}
              </div>
              {head}
            </div>
            {children}
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
