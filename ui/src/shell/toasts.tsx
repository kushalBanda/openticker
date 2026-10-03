import { X } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Tone } from "../lib/events";
import { enter, leave } from "../lib/motion";

export interface Toast {
  text: string;
  /** A badge before the text: Fill, Kill, ... */
  kind?: string;
  tone?: Tone;
  /** A second, quieter line: who and when. */
  note?: string;
  /** Needs the user: outlined in red and shown for longer. */
  urgent?: boolean;
  action?: { label: string; run: () => void };
}

interface Shown extends Toast {
  id: number;
}

const SHOWN_MS = 5_000;
const URGENT_MS = 10_000;
const MOST = 3;

const ToastContext = createContext<((toast: Toast) => void) | null>(null);

/** Shows a toast, bottom right: at most three at once, each for 5 s (10 s when urgent). */
export function useToast(): (toast: Toast) => void {
  const push = useContext(ToastContext);
  if (push === null) throw new Error("useToast needs a ToastProvider");
  return push;
}

function Item({ toast, onClose }: { toast: Shown; onClose: () => void }) {
  const [held, setHeld] = useState(false);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (held) return;
    const timer = setTimeout(() => close.current(), toast.urgent ? URGENT_MS : SHOWN_MS);
    return () => clearTimeout(timer);
  }, [held, toast.urgent]);

  return (
    <m.div
      layout
      className="toast"
      role={toast.urgent ? "alert" : "status"}
      data-testid="toast"
      data-urgent={toast.urgent || undefined}
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      {...enter}
      exit={leave}
    >
      {toast.kind && (
        <span className="badge" data-tone={toast.tone}>
          {toast.kind}
        </span>
      )}
      <div className="toast-body">
        <div className={toast.urgent ? "font-semibold" : undefined}>{toast.text}</div>
        {toast.note && <div className="note">{toast.note}</div>}
      </div>
      {toast.action && (
        <button
          type="button"
          className="btn"
          data-size="sm"
          onClick={() => {
            toast.action?.run();
            onClose();
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button type="button" className="toast-close" aria-label="Dismiss" onClick={onClose}>
        <X size={14} aria-hidden />
      </button>
    </m.div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Shown[]>([]);
  const next = useRef(0);

  const push = useCallback((toast: Toast) => {
    setToasts((all) => [...all, { ...toast, id: ++next.current }].slice(-MOST));
  }, []);
  const remove = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);
  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <section className="toasts" aria-label="Notifications">
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <Item key={toast.id} toast={toast} onClose={() => remove(toast.id)} />
          ))}
        </AnimatePresence>
      </section>
    </ToastContext.Provider>
  );
}
