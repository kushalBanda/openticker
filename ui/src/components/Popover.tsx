import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import {
  type ReactNode,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { duration, ease } from "../lib/motion";

const GAP = 8;

/**
 * A floating panel under the control that opened it (DESIGN.md Elevation:
 * floating): `surface-raised`, the pop shadow, a hairline edge. Portalled,
 * so a tile never clips it; it flips above when there's no room below,
 * and closes on Escape, a click outside, or a scroll of the page.
 */
export function Popover({
  anchor,
  open,
  onClose,
  label,
  align = "end",
  children,
}: {
  anchor: RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  label: string;
  /** Which edge of the anchor the panel lines up with. */
  align?: "start" | "end";
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<{ top: number; left: number; up: boolean }>();

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect();
      const box = panel.current?.getBoundingClientRect();
      if (!rect) return;
      const width = box?.width ?? 320;
      const height = box?.height ?? 360;
      const up = window.innerHeight - rect.bottom < height + GAP + 8 && rect.top > height + GAP;
      const left = align === "end" ? rect.right - width : rect.left;
      setAt({
        top: up ? rect.top - GAP - height : rect.bottom + GAP,
        left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
        up,
      });
    };
    place();
    // Measured once more after the panel has its size.
    const frame = requestAnimationFrame(place);
    return () => cancelAnimationFrame(frame);
  }, [open, anchor, align]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      onClose();
      anchor.current?.focus();
    };
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      onClose();
    };
    const onScroll = (event: Event) => {
      if (panel.current?.contains(event.target as Node)) return;
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onClose);
    };
  }, [open, onClose, anchor]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          ref={panel}
          role="dialog"
          aria-label={label}
          className="float-panel"
          style={{ top: at?.top ?? -9999, left: at?.left ?? -9999 }}
          initial={{ opacity: 0, y: at?.up ? 4 : -4, scale: 0.98 }}
          animate={{
            opacity: 1,
            y: 0,
            scale: 1,
            transition: { duration: duration.fast, ease: ease.out },
          }}
          exit={{ opacity: 0, scale: 0.98, transition: { duration: duration.fast, ease: ease.in } }}
        >
          {children}
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
