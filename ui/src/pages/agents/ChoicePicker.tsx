import { Check, ChevronDown } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Effort, HarnessInfo } from "../../api/queries";
import { effortLabel, harnessLabel } from "../../lib/agents";
import { enter, leave } from "../../lib/motion";

/** A message's own model and effort; null keeps the folder's default. */
export type Choice = { model: string | null; effort: Effort | null };

type Default = { model: string | null; effort: Effort | null };

const GAP = 8;
const MAX_HEIGHT = 460;
const TOP_CLEAR = 64; // the status bar, and a little air

/**
 * The composer's one model and effort picker (ADR 40): the folder's default
 * marked, any other for the next message. Opens upward, over the thread.
 */
export function ChoicePicker({
  harness,
  info,
  folderDefault,
  value,
  onChange,
  disabled,
}: {
  harness: string;
  info: HarnessInfo | undefined;
  folderDefault: Default;
  value: Choice;
  onChange: (choice: Choice) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [typing, setTyping] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [at, setAt] = useState<{ bottom: number; right: number; height: number }>();
  const model = value.model ?? folderDefault.model;
  const effort = value.effort ?? folderDefault.effort;
  const models = info?.models ?? [];
  const custom = model !== null && !models.includes(model);

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

  // Above the button, right edges lined up, never under the status bar.
  const show = () => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    setAt({
      bottom: window.innerHeight - rect.top + GAP,
      right: window.innerWidth - rect.right,
      height: Math.min(MAX_HEIGHT, rect.top - GAP - TOP_CLEAR),
    });
    setOpen(true);
  };

  const close = () => {
    setOpen(false);
    setTyping(false);
    button.current?.focus();
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };
  // The folder's default is chosen by choosing nothing.
  const pickModel = (name: string | null) =>
    onChange({ ...value, model: name === folderDefault.model ? null : name });
  const pickEffort = (level: Effort) =>
    onChange({ ...value, effort: level === folderDefault.effort ? null : level });

  return (
    <>
      <button
        ref={button}
        type="button"
        className="aw-pick"
        aria-label={`Model and effort: ${model ?? "default model"}, ${effortLabel(effort)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
      >
        {model ? <code>{model}</code> : <span>Default</span>}
        {effort && <span className="aw-lvl">{effortLabel(effort)}</span>}
        <ChevronDown aria-hidden />
      </button>
      {createPortal(
        <AnimatePresence>
          {open && at && (
            <m.div
              ref={menu}
              className="menu aw-menu"
              role="menu"
              aria-label="Model and effort"
              style={{ bottom: at.bottom, right: at.right, maxHeight: at.height }}
              onKeyDown={onKey}
              {...enter}
              exit={leave}
            >
              <div className="menu-note">Model · {harnessLabel(harness)}</div>
              {folderDefault.model === null && (
                <Row checked={model === null} hint="default here" onClick={() => pickModel(null)}>
                  Agent's default
                </Row>
              )}
              {models.map((name) => (
                <Row
                  key={name}
                  checked={model === name}
                  hint={folderDefault.model === name ? "default here" : undefined}
                  onClick={() => pickModel(name)}
                >
                  <code>{name}</code>
                </Row>
              ))}
              {typing || (info?.free_text_model ?? false) ? (
                <form
                  className="aw-menu-model"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const typed = new FormData(event.currentTarget).get("model");
                    const name = typeof typed === "string" ? typed.trim() : "";
                    if (name) pickModel(name);
                    setTyping(false);
                  }}
                >
                  <input
                    name="model"
                    className="input"
                    aria-label="Model name"
                    placeholder="Model name"
                    defaultValue={custom ? (model ?? "") : ""}
                    // biome-ignore lint/a11y/noAutofocus: opened by asking to type one
                    autoFocus={typing}
                  />
                </form>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  className="menu-row"
                  onClick={() => setTyping(true)}
                >
                  <span className="aw-menu-check" aria-hidden>
                    {custom && <Check size={14} />}
                  </span>
                  <span className="flex-1">{custom ? <code>{model}</code> : "Other model…"}</span>
                </button>
              )}
              <hr className="aw-menu-rule" />
              <div className="menu-note">Effort</div>
              {(info?.efforts ?? []).map((level) => (
                <Row
                  key={level}
                  checked={effort === level}
                  hint={folderDefault.effort === level ? "default here" : undefined}
                  onClick={() => pickEffort(level)}
                >
                  {effortLabel(level)}
                </Row>
              ))}
            </m.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

function Row({
  checked,
  hint,
  onClick,
  children,
}: {
  checked: boolean;
  hint?: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={checked}
      className="menu-row"
      onClick={onClick}
    >
      <span className="aw-menu-check" aria-hidden>
        {checked && <Check size={14} />}
      </span>
      <span className="flex-1">{children}</span>
      {hint && <span className="aw-menu-hint">{hint}</span>}
    </button>
  );
}
