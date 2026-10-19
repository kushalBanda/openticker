import type { CSSProperties, ReactNode } from "react";

/**
 * A box that scrolls on its own, up and down only (DESIGN.md No sideways
 * scrolling): a thin themed scrollbar, scrolling that stops at its edges
 * instead of moving the page, and a soft fade at whichever edge has more
 * behind it. The fade is CSS scroll-driven; without support it is a plain
 * scroll box.
 */
export function Scroll({
  children,
  max,
  className,
}: {
  children: ReactNode;
  /** The most it grows before it scrolls: 320, or "60vh". */
  max?: number | string;
  className?: string;
}) {
  const style: CSSProperties | undefined = max === undefined ? undefined : { maxHeight: max };
  return (
    <div className={className ? `scroll ${className}` : "scroll"} style={style}>
      {children}
    </div>
  );
}
