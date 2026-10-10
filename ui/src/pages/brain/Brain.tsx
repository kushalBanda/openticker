import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { useBrainGraph, useBrainSearch } from "../../api/queries";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { failureOf, TableFailed } from "../../components/TableStates";
import { BrainGraph } from "./BrainGraph";
import { DebriefLine } from "./DebriefLine";
import { DEFAULT_CONTROLS, type GraphControls, GraphSettings, ScopeControl } from "./GraphSettings";
import type { GraphEngine, GraphFilters, NodeKind } from "./graph/engine";
import { LearningLine } from "./LearningLine";
import { NoteList } from "./Lists";
import { NoteSheet } from "./NoteSheet";

// The sheet's width and its gap from the edge: the graph frames itself clear of it.
const SHEET_COVERS = 392 + 28;
// The settings panel's width and gap, while it is unfolded.
const SETTINGS_COVER = 236 + 28;

type Tab = "graph" | "days" | "lessons" | "proposals";
const PATHS: Record<Tab, string> = {
  graph: "/brain",
  days: "/brain/days",
  lessons: "/brain/lessons",
  proposals: "/brain/proposals",
};

/** The brain: its notes as a graph, or one kind of them as a list. */
export function Brain() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const tab = (Object.keys(PATHS) as Tab[]).find((t) => PATHS[t] === pathname) ?? "graph";
  const open = useBrainSearch({ kind: "proposal", status: "open", limit: 100 });

  return (
    <Page
      title="Brain"
      badges={
        <Segmented
          label="Brain view"
          value={tab}
          onChange={(next) => navigate(PATHS[next])}
          segments={[
            { value: "graph", label: "Graph" },
            { value: "days", label: "Days" },
            { value: "lessons", label: "Lessons" },
            { value: "proposals", label: "Proposals", count: open.data?.notes.length || undefined },
          ]}
        />
      }
      actions={<LearningLine />}
    >
      <DebriefLine />
      {tab === "graph" ? (
        <GraphView />
      ) : (
        <NoteList kind={tab === "days" ? "day" : tab === "lessons" ? "lesson" : "proposal"} />
      )}
    </Page>
  );
}

function GraphView() {
  const graph = useBrainGraph("30");
  const { hash } = useLocation();
  const navigate = useNavigate();
  const selected = decodeURIComponent(hash.slice(1)) || null;
  const point = graph.data?.notes.find((n) => n.note_id === selected) ?? null;
  const select = (id: string | null) =>
    navigate({ hash: id ? `#${id}` : "" }, { replace: true, preventScrollReset: true });
  const failure = failureOf(graph);
  const engine = useRef<GraphEngine | null>(null);
  const find = useRef<HTMLInputElement>(null);
  // Opened at a note (/brain#<id>, from a note's page or its mini graph): around it.
  const [controls, setControls] = useState<GraphControls>(() => ({
    ...loadDisplay(),
    around: Boolean(selected),
  }));
  const change = useCallback((next: Partial<GraphControls>) => {
    setControls((was) => {
      const now = { ...was, ...next };
      saveDisplay(now);
      return now;
    });
  }, []);

  // The settings fold out of the way while a note is open, and come back after.
  const autoFolded = useRef(false);
  const open = point !== null;
  useEffect(() => {
    setControls((was) => {
      if (open && !was.folded) {
        autoFolded.current = true;
        return { ...was, folded: true };
      }
      if (!open && autoFolded.current) {
        autoFolded.current = false;
        return { ...was, folded: false };
      }
      return was;
    });
  }, [open]);

  const filters = useMemo<GraphFilters>(
    () => ({
      hiddenKinds: controls.hiddenKinds,
      hiddenStatuses: controls.hiddenStatuses,
      query: controls.query,
      local: controls.around && point ? { id: point.note_id, depth: controls.depth } : null,
    }),
    [
      controls.hiddenKinds,
      controls.hiddenStatuses,
      controls.query,
      controls.around,
      controls.depth,
      point,
    ],
  );
  const counts = useMemo(() => {
    const kinds: Record<NodeKind, number> = {
      day: 0,
      strategy: 0,
      symbol: 0,
      lesson: 0,
      proposal: 0,
    };
    const statuses: Record<string, number> = {};
    for (const n of graph.data?.notes ?? []) {
      kinds[n.kind] += 1;
      if (n.kind === "lesson" && n.status) statuses[n.status] = (statuses[n.status] ?? 0) + 1;
    }
    return { kinds, statuses };
  }, [graph.data]);

  return (
    <section className="brain-stage" aria-busy={graph.isPending}>
      {graph.data ? (
        graph.data.notes.length === 0 ? (
          <div className="brain-message empty">
            <h2>Nothing in the brain yet</h2>
            <p className="note">
              Every strategy gets a note here, linked to the symbols it trades, and days, lessons
              and proposals join them as they're written.
            </p>
          </div>
        ) : (
          <>
            <BrainGraph
              graph={graph.data}
              selected={point ? point.note_id : null}
              onSelect={select}
              occludeRight={point ? SHEET_COVERS : controls.folded ? 0 : SETTINGS_COVER}
              filters={filters}
              labelAt={controls.labelAt}
              spacing={controls.spacing}
              engineRef={engine}
            />
            <ScopeControl controls={controls} onChange={change} hasSelection={point !== null} />
            <GraphSettings
              controls={controls}
              onChange={change}
              counts={counts.kinds}
              statusCounts={counts.statuses}
              find={find}
              besideSheet={point !== null}
              onFindEnter={() => {
                const id = engine.current?.firstMatch(controls.query);
                if (id) select(id);
              }}
            />
            <NoteSheet point={point} onClose={() => select(null)} />
            <nav className="sr-only" aria-label="Notes in the graph">
              <ul>
                {graph.data.notes.map((n) => (
                  <li key={n.note_id}>
                    <button type="button" onClick={() => select(n.note_id)}>
                      {n.kind}: {n.title}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          </>
        )
      ) : failure ? (
        <div className="brain-message">
          <TableFailed what="The brain" failure={failure} />
        </div>
      ) : (
        <p className="brain-message note" role="status">
          Loading the brain…
        </p>
      )}
    </section>
  );
}

// The display settings are this browser's own: remembered, never required.
const DISPLAY_KEY = "ot.brain.display";

function loadDisplay(): GraphControls {
  try {
    const raw = JSON.parse(localStorage.getItem(DISPLAY_KEY) ?? "null") as {
      labelAt?: number;
      spacing?: number;
      folded?: boolean;
      hiddenKinds?: NodeKind[];
      hiddenStatuses?: string[];
    } | null;
    if (!raw) return DEFAULT_CONTROLS;
    return {
      ...DEFAULT_CONTROLS,
      labelAt: typeof raw.labelAt === "number" ? raw.labelAt : DEFAULT_CONTROLS.labelAt,
      spacing: typeof raw.spacing === "number" ? raw.spacing : DEFAULT_CONTROLS.spacing,
      folded: raw.folded === true,
      hiddenKinds: new Set(raw.hiddenKinds ?? []),
      hiddenStatuses: new Set(raw.hiddenStatuses ?? DEFAULT_CONTROLS.hiddenStatuses),
    };
  } catch {
    return DEFAULT_CONTROLS;
  }
}

function saveDisplay(c: GraphControls) {
  try {
    localStorage.setItem(
      DISPLAY_KEY,
      JSON.stringify({
        labelAt: c.labelAt,
        spacing: c.spacing,
        folded: c.folded,
        hiddenKinds: [...c.hiddenKinds],
        hiddenStatuses: [...c.hiddenStatuses],
      }),
    );
  } catch {
    // Private windows refuse storage; the settings still work for this visit.
  }
}
