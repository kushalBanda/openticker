import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router";
import type { BrainNote } from "../../api/queries";
import { useTheme } from "../../lib/theme";
import { GraphEngine, type GraphLink, type GraphNode } from "./graph/engine";

/**
 * A note and the notes one link away, with the links among them: the same
 * engine as the Brain page, compact. Every label shows; hovering fades the
 * rest; a click opens that note on the Brain page, around it.
 */
export function MiniGraph({ note }: { note: BrainNote }) {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<GraphEngine | null>(null);
  const navigate = useNavigate();
  const open = useRef((id: string) => navigate(`/brain#${id}`));
  open.current = (id: string) => navigate(`/brain#${id}`);
  const reduced = useReducedMotion() ?? false;
  const [theme] = useTheme();

  const nodes = useMemo<GraphNode[]>(() => {
    const byId = new Map<string, GraphNode>();
    for (const n of [note, ...note.links_out, ...note.backlinks]) {
      if (!byId.has(n.note_id)) {
        byId.set(n.note_id, {
          id: n.note_id,
          kind: n.kind,
          label: n.title,
          status: n.status ?? undefined,
        });
      }
    }
    return [...byId.values()];
  }, [note]);
  const links = useMemo<GraphLink[]>(
    () => note.local_links.map((l) => ({ source: l.from_id, target: l.to_id })),
    [note.local_links],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: built once; motion follows below
  useEffect(() => {
    if (!host.current) return;
    const built = new GraphEngine(
      host.current,
      { compact: true, labelAt: 0, spacing: 0.7, reducedMotion: reduced, occludeRight: 0 },
      (id) => {
        if (id) open.current(id);
      },
    );
    engine.current = built;
    return () => {
      built.destroy();
      engine.current = null;
    };
  }, []);
  useEffect(() => {
    engine.current?.setData(nodes, links);
  }, [nodes, links]);
  useEffect(() => {
    engine.current?.setOptions({ reducedMotion: reduced });
  }, [reduced]);
  useEffect(() => {
    void theme;
    const frame = requestAnimationFrame(() => engine.current?.refreshColours());
    return () => cancelAnimationFrame(frame);
  }, [theme]);

  return (
    <section className="tile" aria-labelledby="mini-graph">
      <h2 id="mini-graph" className="tile-title">
        In the graph
      </h2>
      <div ref={host} className="brain-mini" data-testid="mini-graph" />
      <p className="note brain-mini-note">
        {nodes.length - 1 === 0
          ? "Nothing links here yet."
          : `${nodes.length - 1} linked ${nodes.length - 1 === 1 ? "note" : "notes"}. Click one to open it in the graph.`}
      </p>
    </section>
  );
}
