import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * Text to paste somewhere else: a request for an agent, an alert URL
 * (DESIGN.md Command Line). The button says when it has copied.
 */
export function CopyLine({ text, shown, label }: { text: string; shown?: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1_600);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <div className="command-line">
      <span className="min-w-0 flex-1 truncate" title={shown ?? text}>
        {shown ?? text}
      </span>
      <button
        type="button"
        className="copy-button"
        aria-label={copied ? "Copied" : label}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
          } catch {
            setCopied(false);
          }
        }}
      >
        {copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
      </button>
    </div>
  );
}
