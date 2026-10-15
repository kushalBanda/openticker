import { useEffect, useRef, useState } from "react";
import { MISSING, rupees } from "../../lib/format";
import { parseRupees } from "../../lib/manager";

/**
 * A rupee amount the user can change in place: a button showing it, an
 * input while editing. Enter or leaving the field saves, Esc cancels.
 */
export function Amount({
  value,
  label,
  onSave,
  normalize = (v) => v,
  disabled,
}: {
  value: number | null;
  /** For screen readers: "Straddle's stop". */
  label: string;
  onSave: (value: number | null) => Promise<unknown>;
  normalize?: (value: number) => number;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  const shown = value === null ? MISSING : rupees(value, { decimals: 0 });
  if (!editing) {
    return (
      <button
        type="button"
        className="amount-edit"
        aria-label={`Change ${label}: ${shown}`}
        disabled={disabled}
        onClick={() => {
          setText(value === null ? "" : String(value));
          setError(false);
          setEditing(true);
        }}
      >
        {shown}
      </button>
    );
  }
  const save = async () => {
    const parsed = parseRupees(text);
    if (parsed === undefined) {
      setError(true);
      return;
    }
    const next = parsed === null ? null : normalize(parsed);
    if (next === value) {
      setEditing(false);
      return;
    }
    try {
      await onSave(next);
      setEditing(false);
    } catch {
      setError(true);
    }
  };
  return (
    <input
      ref={input}
      className="input amount-input"
      aria-label={label}
      aria-invalid={error}
      inputMode="decimal"
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        setError(false);
      }}
      onBlur={() => void save()}
      onKeyDown={(e) => {
        if (e.key === "Enter") void save();
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}
