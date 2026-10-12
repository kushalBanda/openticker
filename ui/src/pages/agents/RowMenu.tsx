import { Archive, Ellipsis, Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AgentThreadSummary } from "../../api/queries";
import { enter, leave } from "../../lib/motion";

const GAP = 4;
const WIDTH = 200;

/** A chat row's ⋯ menu (ADR 40): Rename, Pin, Archive, Delete. */
export function RowMenu({
  thread,
  onRename,
  onPin,
  onArchive,
  onDelete,
}: {
  thread: AgentThreadSummary;
  onRename: () => void;
  onPin: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const working = thread.last_status != null && thread.last_status !== "ended";

  useEffect(() => {
    if (!at) return;
    menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menu.current?.contains(target) && !button.current?.contains(target)) setAt(null);
    };
    const shut = () => setAt(null);
    window.addEventListener("pointerdown", away);
    window.addEventListener("resize", shut);
    return () => {
      window.removeEventListener("pointerdown", away);
      window.removeEventListener("resize", shut);
    };
  }, [at]);

  const open = () => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    const top = Math.min(rect.bottom + GAP, window.innerHeight - 190);
    setAt({ top, left: Math.min(rect.left, window.innerWidth - WIDTH - 8) });
  };
  const close = () => {
    setAt(null);
    button.current?.focus();
  };
  const pick = (run: () => void) => () => {
    setAt(null);
    run();
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])].filter(
      (b) => !b.disabled,
    );
    const now = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "ArrowDown" ? now + 1 : now - 1;
    items[(next + items.length) % items.length]?.focus();
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        className="aw-ico"
        aria-label={`More for ${thread.title}`}
        aria-haspopup="menu"
        aria-expanded={at !== null}
        onClick={() => (at ? setAt(null) : open())}
      >
        <Ellipsis aria-hidden />
      </button>
      {createPortal(
        <AnimatePresence>
          {at && (
            <m.div
              ref={menu}
              className="menu aw-row-menu"
              role="menu"
              aria-label={`${thread.title}`}
              style={{ top: at.top, left: at.left }}
              onKeyDown={onKey}
              {...enter}
              exit={leave}
            >
              <button type="button" role="menuitem" className="menu-row" onClick={pick(onRename)}>
                <Pencil aria-hidden />
                Rename
              </button>
              <button type="button" role="menuitem" className="menu-row" onClick={pick(onPin)}>
                {thread.pinned ? <PinOff aria-hidden /> : <Pin aria-hidden />}
                {thread.pinned ? "Unpin" : "Pin"}
              </button>
              <button
                type="button"
                role="menuitem"
                className="menu-row"
                disabled={working}
                title={working ? "Stop the agent to archive this chat" : undefined}
                onClick={pick(onArchive)}
              >
                <Archive aria-hidden />
                Archive
              </button>
              <hr className="aw-menu-rule" />
              <button
                type="button"
                role="menuitem"
                className="menu-row aw-danger"
                disabled={working}
                title={working ? "Stop the agent to delete this chat" : undefined}
                onClick={pick(onDelete)}
              >
                <Trash2 aria-hidden />
                Delete…
              </button>
            </m.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
