import { Info } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { duration, ease } from "../lib/motion";

const WIDTH = 240;

/**
 * A figure with an info mark that shows more about it in a glass popover
 * (DESIGN.md): on hover or focus, or a tap on touch screens. Portalled, so
 * a table's scroll never clips it.
 */
export function InfoPopover({
  children,
  label,
  title,
  content,
}: {
  children: ReactNode;
  /** What the button says to a screen reader: "Charges on this fill". */
  label: string;
  title: string;
  content: ReactNode;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);

  const show = () => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.min(Math.max(8, rect.right - WIDTH), window.innerWidth - WIDTH - 8);
    setAt({ top: rect.bottom + 6, left });
  };
  const hide = () => setAt(null);

  const open = at !== null;
  useEffect(() => {
    if (!open) return;
    const close = () => setAt(null);
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        type="button"
        className="info-trigger"
        aria-label={label}
        aria-expanded={at !== null}
        aria-controls={at ? id : undefined}
        onPointerEnter={(event) => event.pointerType === "mouse" && show()}
        onPointerLeave={(event) => event.pointerType === "mouse" && hide()}
        onFocus={show}
        onBlur={hide}
        onClick={() => (at ? hide() : show())}
      >
        {children}
        <Info aria-hidden />
      </button>
      {createPortal(
        <AnimatePresence>
          {at && (
            <m.div
              id={id}
              role="tooltip"
              className="popover"
              style={{ top: at.top, left: at.left, width: WIDTH }}
              initial={{ opacity: 0, y: -4 }}
              animate={{
                opacity: 1,
                y: 0,
                transition: { duration: duration.fast, ease: ease.out },
              }}
              exit={{ opacity: 0, transition: { duration: duration.fast, ease: ease.in } }}
            >
              <div className="label">{title}</div>
              {content}
            </m.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
