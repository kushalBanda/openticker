import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  GraphEngine,
  type GraphLink,
  type GraphNode,
  NO_FILTERS,
} from "../../src/pages/brain/graph/engine";

// jsdom draws nothing: a canvas context whose every call does nothing, and no resizes.
beforeEach(() => {
  const ctx = new Proxy(
    {},
    {
      get: (_, key) => (key === "measureText" ? () => ({ width: 10 }) : () => undefined),
      set: () => true,
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const options = { compact: false, labelAt: 1, spacing: 1, reducedMotion: true, occludeRight: 0 };
const nodes: GraphNode[] = [
  { id: "stg", kind: "strategy", label: "Straddle" },
  { id: "les", kind: "lesson", label: "Exit by 11:00", status: "hunch" },
  { id: "day", kind: "day", label: "Mon 5 Oct", net: 120 },
  { id: "sym", kind: "symbol", label: "NIFTY 50" },
];
const links: GraphLink[] = [
  { source: "les", target: "stg" },
  { source: "day", target: "stg" },
  { source: "stg", target: "sym" },
];

test("setData_reheats_only_on_set_change", () => {
  const engine = new GraphEngine(document.createElement("div"), options, () => {});

  expect(engine.setData(nodes, links)).toBe(true);
  // A status or a title changing (a check, an edit) keeps the layout still.
  const renamed = nodes.map((n) => (n.id === "les" ? { ...n, status: "tested", label: "x" } : n));
  expect(engine.setData(renamed, [...links].reverse())).toBe(false);
  // A new note, or a new link, stirs it.
  expect(engine.setData([...renamed, { id: "prp", kind: "proposal", label: "P" }], links)).toBe(
    true,
  );
  expect(engine.setData(renamed, [...links, { source: "day", target: "les" }])).toBe(true);
  engine.destroy();
});

test("filters and Around selection decide what is shown", () => {
  const engine = new GraphEngine(document.createElement("div"), options, () => {});
  engine.setData(nodes, links);
  expect(engine.shown()).toEqual({ notes: 4, links: 3 });

  engine.setFilters({ ...NO_FILTERS, hiddenKinds: new Set(["symbol"]) });
  expect(engine.shown()).toEqual({ notes: 3, links: 2 });
  engine.setFilters({ ...NO_FILTERS, local: { id: "les", depth: 1 } });
  expect(engine.shown()).toEqual({ notes: 2, links: 1 });
  engine.setFilters({ ...NO_FILTERS, local: { id: "les", depth: 2 } });
  expect(engine.shown()).toEqual({ notes: 4, links: 3 });
  expect(engine.firstMatch("nifty")).toBe("sym");
  expect(engine.firstMatch("  ")).toBeNull();
  engine.destroy();
});
