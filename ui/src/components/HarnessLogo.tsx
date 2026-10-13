import claudeCode from "@lobehub/icons-static-svg/icons/claudecode-color.svg";
import codex from "@lobehub/icons-static-svg/icons/codex-color.svg";

// Each coding agent's own mark (LobeHub's icon set, MIT), so the two are told
// apart at a glance wherever one is picked or shown.
const LOGOS: Record<string, string> = { claude: claudeCode, codex };

/** Decorative: the agent's name is always written beside it. */
export function HarnessLogo({ harness, size = 16 }: { harness: string; size?: number }) {
  const src = LOGOS[harness];
  if (!src) return null;
  return (
    <img
      className="harness-logo"
      src={src}
      alt=""
      aria-hidden
      width={size}
      height={size}
      draggable={false}
    />
  );
}
