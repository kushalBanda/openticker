// The graph's colours come from the design tokens, read again when the theme
// changes, so the canvas always matches the rest of the page.

export interface Palette {
  surface: string;
  ink: string;
  muted: string;
  line: string;
  up: string;
  down: string;
  warn: string;
  link: string;
  accent: string;
  brand: string;
  focus: string;
}

export function readPalette(element: Element = document.documentElement): Palette {
  const style = getComputedStyle(element);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return {
    surface: token("--surface"),
    ink: token("--ink"),
    muted: token("--ink-muted"),
    line: token("--line-strong"),
    up: token("--up"),
    down: token("--down"),
    warn: token("--warn"),
    link: token("--link"),
    accent: token("--accent-ink"),
    brand: token("--accent"),
    focus: token("--focus"),
  };
}

/** A point's colour: a day by whether it made money after costs, a lesson by
 * its status, a proposal by its state. */
export function nodeColour(
  node: { kind: string; status?: string | undefined; net?: number | null | undefined },
  p: Palette,
): string {
  switch (node.kind) {
    case "day":
      return node.net == null ? p.muted : node.net >= 0 ? p.up : p.down;
    case "strategy":
      return p.accent;
    case "lesson":
      return (
        { hunch: p.warn, tested: p.ink, rule: p.up, retired: p.muted }[node.status ?? ""] ?? p.ink
      );
    case "proposal":
      return (
        { open: p.link, accepted: p.up, rejected: p.muted, later: p.muted }[node.status ?? ""] ??
        p.link
      );
    default:
      return p.muted;
  }
}
