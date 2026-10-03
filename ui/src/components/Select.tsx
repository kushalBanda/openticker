import { Check, ChevronDown } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { duration, ease } from "../lib/motion";

export interface Option<T extends string> {
  value: T;
  label: string;
  /** Quieter, on the right: "29 d", "running". */
  hint?: string;
}

const GAP = 6;
const MAX_HEIGHT = 320;

/**
 * Every dropdown in the app (DESIGN.md): a pill with a chevron that opens an
 * opaque list under it, the chosen one ticked. The keyboard works as in a
 * native select (arrows, Home / End, a letter to jump, Enter, Escape), and
 * screen readers hear a combobox with its listbox. Portalled, so a tile or
 * a dialog never clips it.
 */
export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  placeholder,
  className,
}: {
  /** What the control is, for a screen reader: "Later expiries". */
  label: string;
  /** Not one of the options: the pill shows the placeholder. */
  value: T | "";
  options: Option<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  className?: string;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [at, setAt] = useState<{ top: number; left: number; width: number; up: boolean }>();
  const chosen = options.find((o) => o.value === value);

  const place = useCallback(() => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    const below = window.innerHeight - rect.bottom - GAP - 8;
    const up = below < Math.min(MAX_HEIGHT, options.length * 34 + 12) && rect.top > below;
    setAt({
      top: up ? rect.top - GAP : rect.bottom + GAP,
      left: Math.min(rect.left, window.innerWidth - Math.max(rect.width, 200) - 8),
      width: rect.width,
      up,
    });
  }, [options.length]);

  const show = (start?: "first" | "last") => {
    const index = options.findIndex((o) => o.value === value);
    setActive(start === "last" ? options.length - 1 : start === "first" || index < 0 ? 0 : index);
    place();
    setOpen(true);
  };
  const hide = (refocus = true) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };
  const choose = (index: number) => {
    const option = options[index];
    if (option) onChange(option.value);
    hide();
  };

  useLayoutEffect(() => {
    if (open) list.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!list.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    const away = () => setOpen(false);
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("resize", away);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("resize", away);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, place]);

  // The active row stays in view as the arrows move it.
  useEffect(() => {
    if (open)
      list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const onButtonKey = (event: KeyboardEvent) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      show(event.key === "ArrowUp" ? "last" : undefined);
    }
  };

  const onListKey = (event: KeyboardEvent) => {
    const last = options.length - 1;
    const move: Record<string, number> = {
      ArrowDown: Math.min(last, active + 1),
      ArrowUp: Math.max(0, active - 1),
      Home: 0,
      End: last,
      PageDown: Math.min(last, active + 8),
      PageUp: Math.max(0, active - 8),
    };
    if (event.key in move) {
      event.preventDefault();
      setActive(move[event.key] ?? active);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // the list closes, not the dialog it's in
      hide();
    } else if (event.key === "Tab") {
      hide(false);
    } else if (event.key.length === 1 && /\S/.test(event.key)) {
      // A letter or digit jumps to the next option starting with it.
      const key = event.key.toLowerCase();
      const order = [...options.slice(active + 1), ...options.slice(0, active + 1)];
      const next = order.find((o) => o.label.toLowerCase().startsWith(key));
      if (next) setActive(options.indexOf(next));
    }
  };

  const optionId = (index: number) => `${id}-option-${index}`;

  return (
    <>
      <button
        ref={button}
        type="button"
        role="combobox"
        className={`select-btn ${className ?? ""}`}
        data-chosen={chosen !== undefined}
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => (open ? hide() : show())}
        onKeyDown={onButtonKey}
      >
        <span className="select-value">{chosen?.label ?? placeholder ?? label}</span>
        <ChevronDown size={15} aria-hidden className="select-chevron" />
      </button>
      {createPortal(
        <AnimatePresence>
          {open && at && (
            <m.div
              ref={list}
              id={id}
              role="listbox"
              aria-label={label}
              aria-activedescendant={optionId(active)}
              tabIndex={-1}
              className="select-list"
              data-up={at.up}
              style={{
                left: at.left,
                minWidth: Math.max(at.width, 200),
                maxHeight: MAX_HEIGHT,
                ...(at.up ? { bottom: window.innerHeight - at.top } : { top: at.top }),
              }}
              onKeyDown={onListKey}
              initial={{ opacity: 0, y: at.up ? 4 : -4 }}
              animate={{
                opacity: 1,
                y: 0,
                transition: { duration: duration.fast, ease: ease.out },
              }}
              exit={{ opacity: 0, transition: { duration: duration.fast } }}
            >
              {options.map((option, index) => (
                // The listbox takes the keys, pointing at an option by
                // aria-activedescendant; an option itself is never focused.
                // biome-ignore lint/a11y/useKeyWithClickEvents: see above
                <div
                  tabIndex={-1}
                  key={option.value}
                  id={optionId(index)}
                  role="option"
                  aria-selected={option.value === value}
                  data-index={index}
                  data-active={index === active}
                  className="select-option"
                  onPointerMove={() => setActive(index)}
                  onClick={() => choose(index)}
                >
                  <span className="select-check" aria-hidden>
                    {option.value === value && <Check size={14} />}
                  </span>
                  <span className="flex-1">{option.label}</span>
                  {option.hint && <span className="select-hint">{option.hint}</span>}
                </div>
              ))}
            </m.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
