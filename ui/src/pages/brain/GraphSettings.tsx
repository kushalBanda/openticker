import { Search, SlidersHorizontal } from "lucide-react";
import { type RefObject, useEffect } from "react";
import { Segmented } from "../../components/Segmented";
import { typing } from "../../shell/Sidebar";
import type { NodeKind } from "./graph/engine";

export interface GraphControls {
  hiddenKinds: Set<NodeKind>;
  hiddenStatuses: Set<string>;
  query: string;
  around: boolean;
  depth: 1 | 2 | 3;
  /** The zoom at which every label shows; 0 shows them always. */
  labelAt: number;
  spacing: number;
  folded: boolean;
}

export const DEFAULT_CONTROLS: GraphControls = {
  hiddenKinds: new Set(),
  hiddenStatuses: new Set(["retired"]),
  query: "",
  around: false,
  depth: 2,
  labelAt: 1,
  spacing: 1,
  folded: false,
};

/** What can be filtered, in the graph's own marks (DESIGN.md roles). */
const KINDS: { kind: NodeKind; label: string; mark: string }[] = [
  { kind: "day", label: "Days", mark: "ring up" },
  { kind: "strategy", label: "Strategies", mark: "brand" },
  { kind: "symbol", label: "Symbols", mark: "small muted" },
  { kind: "lesson", label: "Lessons", mark: "ink" },
  { kind: "proposal", label: "Proposals", mark: "square link" },
];
const STATUSES: { status: string; label: string; mark: string }[] = [
  { status: "hunch", label: "Hunch", mark: "warn" },
  { status: "tested", label: "Tested", mark: "ink" },
  { status: "rule", label: "Rule", mark: "up" },
  { status: "retired", label: "Retired", mark: "dashed muted" },
];

function toggled<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

/** The graph's scope, top left: the whole brain, or around the selected note. */
export function ScopeControl({
  controls,
  onChange,
  hasSelection,
}: {
  controls: GraphControls;
  onChange: (next: Partial<GraphControls>) => void;
  hasSelection: boolean;
}) {
  return (
    <div className="brain-scope">
      <Segmented<"whole" | "around">
        label="Scope"
        value={controls.around ? "around" : "whole"}
        onChange={(v) => onChange({ around: v === "around" })}
        segments={[
          { value: "whole", label: "Whole brain" },
          { value: "around", label: "Around selection" },
        ]}
      />
      {controls.around &&
        (hasSelection ? (
          <div className="brain-depth">
            <span className="note">Depth</span>
            <Segmented<"1" | "2" | "3">
              label="Depth"
              value={String(controls.depth) as "1" | "2" | "3"}
              onChange={(v) => onChange({ depth: Number(v) as 1 | 2 | 3 })}
              segments={[
                { value: "1", label: "1" },
                { value: "2", label: "2" },
                { value: "3", label: "3" },
              ]}
            />
          </div>
        ) : (
          <span className="note brain-depth">Pick a note to see around it</span>
        ))}
    </div>
  );
}

/**
 * The graph's settings, top right (Obsidian's graph panel): find a note,
 * show or hide kinds and lesson statuses, and when labels show and how far
 * apart notes sit. Folds to one button.
 */
export function GraphSettings({
  controls,
  onChange,
  counts,
  statusCounts,
  find,
  onFindEnter,
  besideSheet,
}: {
  controls: GraphControls;
  onChange: (next: Partial<GraphControls>) => void;
  counts: Record<NodeKind, number>;
  statusCounts: Record<string, number>;
  find: RefObject<HTMLInputElement | null>;
  onFindEnter: () => void;
  /** A note is open: the settings sit to its left. */
  besideSheet: boolean;
}) {
  // "/" finds a note, as in Obsidian.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      e.preventDefault();
      onChange({ folded: false });
      requestAnimationFrame(() => find.current?.focus());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [find, onChange]);

  const labels = controls.labelAt === 0 ? "always" : `at ${Math.round(controls.labelAt * 100)}%`;
  return (
    <aside
      className="brain-settings"
      data-folded={controls.folded}
      data-beside-sheet={besideSheet}
      aria-label="Graph settings"
      data-testid="graph-settings"
    >
      <div className="brain-settings-head">
        <span>Graph</span>
        <button
          type="button"
          className="brain-fold"
          aria-label={controls.folded ? "Show graph settings" : "Hide graph settings"}
          aria-expanded={!controls.folded}
          onClick={() => onChange({ folded: !controls.folded })}
        >
          <SlidersHorizontal size={16} aria-hidden />
        </button>
      </div>
      {!controls.folded && (
        <div className="brain-settings-body">
          <label className="brain-find">
            <Search size={14} aria-hidden />
            <input
              ref={find}
              value={controls.query}
              placeholder="Find a note"
              aria-label="Find a note"
              autoComplete="off"
              onChange={(e) => onChange({ query: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") onFindEnter();
                if (e.key === "Escape") {
                  e.stopPropagation();
                  onChange({ query: "" });
                  e.currentTarget.blur();
                }
              }}
            />
            <kbd>/</kbd>
          </label>
          <details open>
            <summary>Show</summary>
            <div className="brain-toggles">
              {KINDS.map(({ kind, label, mark }) => (
                <button
                  key={kind}
                  type="button"
                  className="brain-toggle"
                  aria-pressed={!controls.hiddenKinds.has(kind)}
                  onClick={() => onChange({ hiddenKinds: toggled(controls.hiddenKinds, kind) })}
                >
                  <span className="brain-mark" data-mark={mark} aria-hidden />
                  {label}
                  <i>{counts[kind]}</i>
                </button>
              ))}
            </div>
          </details>
          <details open>
            <summary>Lessons</summary>
            <div className="brain-toggles">
              {STATUSES.map(({ status, label, mark }) => (
                <button
                  key={status}
                  type="button"
                  className="brain-toggle"
                  aria-pressed={!controls.hiddenStatuses.has(status)}
                  onClick={() =>
                    onChange({ hiddenStatuses: toggled(controls.hiddenStatuses, status) })
                  }
                >
                  <span className="brain-mark" data-mark={mark} aria-hidden />
                  {label}
                  <i>{statusCounts[status] ?? 0}</i>
                </button>
              ))}
            </div>
          </details>
          <details>
            <summary>Display</summary>
            <div className="brain-slider">
              <span>Labels</span>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={controls.labelAt}
                aria-label="Zoom at which labels appear"
                aria-valuetext={labels}
                onChange={(e) => onChange({ labelAt: Number(e.target.value) })}
              />
              <span className="note">{labels}</span>
            </div>
            <div className="brain-slider">
              <span>Spacing</span>
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={controls.spacing}
                aria-label="Spacing between notes"
                onChange={(e) => onChange({ spacing: Number(e.target.value) })}
              />
            </div>
            <p className="note brain-hint">
              Days show their net after costs: a green ring made money, a red one lost. Open
              proposals are blue: they wait on you.
            </p>
          </details>
        </div>
      )}
    </aside>
  );
}
