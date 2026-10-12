import { ArrowLeftRight, Check, ChevronDown, Eye, Lock } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Access } from "../../api/queries";
import { enter, leave } from "../../lib/motion";

const GAP = 8;

const ACCESS: Record<Access, { label: string; says: string; Icon: typeof Eye }> = {
  read: {
    label: "Read only",
    says: "Reads your desk, market data and the brain. Changes nothing.",
    Icon: Eye,
  },
  trade: {
    label: "Paper trades",
    says: "Can also place paper orders and change strategies, watchlists and notes. Never broker sign-in, keys or agent jobs.",
    Icon: ArrowLeftRight,
  },
};

/** What a new chat's agent may do on the desk (ADR 40), chosen before its
 * first message: its key decides, since no one approves a step mid-run. */
export function AccessPicker({
  value,
  onChange,
}: {
  value: Access;
  onChange: (access: Access) => void;
}) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<{ bottom: number; left: number }>();
  const menu = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const { label, Icon } = ACCESS[value];

  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menu.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    const shut = () => setOpen(false);
    window.addEventListener("pointerdown", away);
    window.addEventListener("resize", shut);
    return () => {
      window.removeEventListener("pointerdown", away);
      window.removeEventListener("resize", shut);
    };
  }, [open]);

  // Above the button, left edges lined up.
  const show = () => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    setAt({ bottom: window.innerHeight - rect.top + GAP, left: rect.left });
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        className="aw-pick aw-access"
        aria-label={`What the agent may do: ${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : show())}
      >
        <Icon aria-hidden />
        <span>{label}</span>
        <ChevronDown aria-hidden />
      </button>
      {createPortal(
        <AnimatePresence>
          {open && at && (
            <m.div
              ref={menu}
              className="menu aw-menu aw-access-menu"
              role="menu"
              aria-label="What the agent may do"
              style={{ bottom: at.bottom, left: at.left }}
              onKeyDown={onKey}
              {...enter}
              exit={leave}
            >
              {(Object.keys(ACCESS) as Access[]).map((access) => {
                const item = ACCESS[access];
                return (
                  <button
                    key={access}
                    type="button"
                    role="menuitemradio"
                    aria-checked={access === value}
                    className="menu-row aw-access-row"
                    onClick={() => {
                      onChange(access);
                      close();
                    }}
                  >
                    <item.Icon aria-hidden />
                    <span className="flex-1">
                      <b>{item.label}</b>
                      <span>{item.says}</span>
                    </span>
                    <span className="aw-menu-check" aria-hidden>
                      {access === value && <Check size={14} />}
                    </span>
                  </button>
                );
              })}
            </m.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

/** A chat's access once it began: fixed, like its harness. */
export function AccessChip({ access }: { access: Access }) {
  const { label, Icon } = ACCESS[access];
  return (
    <span className="aw-chip" title="Fixed after the first message">
      <Lock aria-hidden />
      <Icon aria-hidden />
      {label}
    </span>
  );
}
