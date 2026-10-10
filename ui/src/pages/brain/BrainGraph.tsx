import { Maximize, Minus, Plus } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import type { BrainGraph as Graph } from "../../api/queries";
import { useTheme } from "../../lib/theme";
import { typing } from "../../shell/Sidebar";
import {
  GraphEngine,
  type GraphFilters,
  type GraphLink,
  type GraphNode,
  NO_FILTERS,
} from "./graph/engine";

/** The brain's notes as a graph, drawn by the one engine. */
export function BrainGraph({
  graph,
  selected,
  onSelect,
  occludeRight,
  filters = NO_FILTERS,
  labelAt = 1,
  spacing = 1,
  engineRef,
}: {
  graph: Graph;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Pixels on the right covered by the note sheet or the settings. */
  occludeRight: number;
  filters?: GraphFilters;
  labelAt?: number;
  spacing?: number;
  /** The engine, for the settings' find box. */
  engineRef?: RefObject<GraphEngine | null>;
}) {
  const host = useRef<HTMLDivElement>(null);
  const own = useRef<GraphEngine | null>(null);
  const engine = engineRef ?? own;
  const [shown, setShown] = useState<{ notes: number; links: number } | null>(null);
  const select = useRef(onSelect);
  select.current = onSelect;
  const reduced = useReducedMotion() ?? false;
  const [theme] = useTheme();

  const nodes = useMemo<GraphNode[]>(
    () =>
      graph.notes.map((n) => ({
        id: n.note_id,
        kind: n.kind,
        label: n.title,
        status: n.status ?? undefined,
        net: n.net,
      })),
    [graph.notes],
  );
  const links = useMemo<GraphLink[]>(
    () => graph.links.map((l) => ({ source: l.from_id, target: l.to_id })),
    [graph.links],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: built once; options follow below
  useEffect(() => {
    if (!host.current) return;
    const built = new GraphEngine(
      host.current,
      { compact: false, labelAt, spacing, reducedMotion: reduced, occludeRight },
      (id) => select.current(id),
    );
    engine.current = built;
    return () => {
      built.destroy();
      engine.current = null;
    };
  }, []);

  // Filters before data and selection: an opening "Around selection" lays
  // out only the notes it shows.
  useEffect(() => {
    engine.current?.setFilters(filters);
    setShown(engine.current?.shown() ?? null);
  }, [filters, engine]);
  useEffect(() => {
    engine.current?.setData(nodes, links);
    setShown(engine.current?.shown() ?? null);
  }, [nodes, links, engine]);
  useEffect(() => {
    engine.current?.select(selected);
    setShown(engine.current?.shown() ?? null);
  }, [selected, engine]);
  useEffect(() => {
    engine.current?.setOptions({ occludeRight, reducedMotion: reduced, labelAt, spacing });
  }, [occludeRight, reduced, labelAt, spacing, engine]);
  useEffect(() => {
    // The theme's tokens are in place by the next frame.
    void theme;
    const frame = requestAnimationFrame(() => engine.current?.refreshColours());
    return () => cancelAnimationFrame(frame);
  }, [theme, engine]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      if (e.key === "f") engine.current?.fitView(500);
      if (e.key === "Escape") select.current(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [engine]);

  return (
    <>
      <div ref={host} className="brain-field" data-testid="brain-graph" />
      <div className="brain-hud">
        <div className="brain-zoom">
          <button type="button" aria-label="Zoom in" onClick={() => engine.current?.zoomBy(1.35)}>
            <Plus size={15} aria-hidden />
          </button>
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => engine.current?.zoomBy(1 / 1.35)}
          >
            <Minus size={15} aria-hidden />
          </button>
          <button
            type="button"
            aria-label="Fit to view"
            onClick={() => engine.current?.fitView(500)}
          >
            <Maximize size={15} aria-hidden />
          </button>
        </div>
        <span className="brain-count" data-testid="graph-count">
          {shown && shown.notes < graph.notes.length
            ? `${shown.notes} of ${graph.notes.length} notes · ${shown.links} links`
            : `${graph.notes.length} notes · ${graph.links.length} links`}
        </span>
      </div>
      {shown?.notes === 0 && (
        <div className="brain-message brain-filtered" role="status">
          Nothing matches these filters.
        </div>
      )}
    </>
  );
}
