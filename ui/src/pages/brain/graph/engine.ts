// The brain's graph: one engine on canvas (d3-force, d3-zoom, d3-drag), used
// full size on the Brain page and compact as a note's mini graph. Points
// settle under a live simulation; hovering one fades all but it and its
// neighbours; labels fade in with zoom and never overlap.

import { drag } from "d3-drag";
import { easeCubicOut } from "d3-ease";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { select } from "d3-selection";
import "d3-transition";
import { type ZoomBehavior, type ZoomTransform, zoom, zoomIdentity } from "d3-zoom";
import { nodeColour, type Palette, readPalette } from "./colours";
import { type LabelCandidate, placeLabels } from "./labels";

export type NodeKind = "day" | "strategy" | "symbol" | "lesson" | "proposal";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  status?: string | undefined;
  net?: number | null | undefined;
}

export interface GraphLink {
  source: string;
  target: string;
}

export interface GraphFilters {
  hiddenKinds: Set<NodeKind>;
  hiddenStatuses: Set<string>;
  query: string;
  /** Only the points within `depth` links of `id` (Obsidian's local graph). */
  local: { id: string; depth: 1 | 2 | 3 } | null;
}

export interface GraphOptions {
  /** A mini graph: every label shown, no selection ring. */
  compact: boolean;
  /** The zoom at which every label shows; 0 shows them always. */
  labelAt: number;
  spacing: number;
  reducedMotion: boolean;
  /** Pixels on the right covered by something floating over the graph. */
  occludeRight: number;
}

const RADIUS: Record<NodeKind, number> = {
  day: 4.5,
  strategy: 7,
  symbol: 3.5,
  lesson: 5.5,
  proposal: 4.5,
};
const FONT = '500 11.5px "Inter Variable", -apple-system, BlinkMacSystemFont, sans-serif';
const CHARGE = -260;
const FADED = 0.12;
const SETTLE_MS = 120;

interface SimNode extends SimulationNodeDatum, GraphNode {
  x: number;
  y: number;
  r: number;
  /** Shown alpha, and the alpha it eases toward. */
  a: number;
  ta: number;
  /** Shown label alpha, and the one it eases toward (null: follow the zoom). */
  la: number;
  tl: number | null;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  source: SimNode;
  target: SimNode;
}

const smooth = (x: number) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));

export const NO_FILTERS: GraphFilters = {
  hiddenKinds: new Set(),
  hiddenStatuses: new Set(),
  query: "",
  local: null,
};

export class GraphEngine {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly sim: Simulation<SimNode, SimLink>;
  private readonly zoom: ZoomBehavior<HTMLCanvasElement, unknown>;
  private readonly resizer: ResizeObserver;
  private options: GraphOptions;
  private filters: GraphFilters = NO_FILTERS;
  private palette: Palette;
  private t: ZoomTransform = zoomIdentity;
  private width = 0;
  private height = 0;
  private dpr = 1;
  private raf = 0;
  private fitted = false;

  /** Every point we were given, kept by id so positions survive new data. */
  private byId = new Map<string, SimNode>();
  private allLinks: GraphLink[] = [];
  private adjacent = new Map<string, Set<string>>();
  private signature = "";

  private nodes: SimNode[] = [];
  private links: SimLink[] = [];
  private hover: string | null = null;
  private selected: string | null = null;
  private dragging: SimNode | null = null;

  constructor(
    private readonly host: HTMLElement,
    options: GraphOptions,
    private readonly onSelect: (id: string | null) => void,
  ) {
    this.options = options;
    this.palette = readPalette();
    this.canvas = document.createElement("canvas");
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", "Graph of the brain's notes");
    host.appendChild(this.canvas);
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("This browser can't draw on a canvas");
    this.ctx = ctx;

    this.sim = forceSimulation<SimNode, SimLink>()
      .force(
        "link",
        forceLink<SimNode, SimLink>()
          .id((d) => d.id)
          .distance((l) => 54 + (l.source.r + l.target.r) * 2.4)
          .strength(0.5),
      )
      .force("charge", forceManyBody<SimNode>().strength(CHARGE).distanceMax(480))
      .force("x", forceX<SimNode>().strength(0.03))
      .force("y", forceY<SimNode>().strength(0.075))
      .force(
        "collide",
        forceCollide<SimNode>((d) => d.r + 8),
      )
      .alphaDecay(0.022)
      .velocityDecay(0.38)
      .on("tick", () => this.request());
    this.sim.stop();

    this.zoom = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.3, 4])
      // A mini graph sits in a page that scrolls: the wheel scrolls the page.
      .filter((e: MouseEvent) => {
        if (this.options.compact && e.type === "wheel") return false;
        return (!e.ctrlKey || e.type === "wheel") && !e.button; // d3-zoom's own default
      })
      .on("zoom", (e: { transform: ZoomTransform }) => {
        this.t = e.transform;
        this.request();
      });

    const dragging = drag<HTMLCanvasElement, unknown, SimNode | undefined>()
      .container(this.canvas)
      .subject((e: { x: number; y: number }) => this.pick(e.x, e.y))
      .on("start", (e: { subject: SimNode }) => {
        this.dragging = e.subject;
        this.canvas.style.cursor = "grabbing";
        if (!this.options.reducedMotion) this.sim.alphaTarget(0.25).restart();
        e.subject.fx = e.subject.x;
        e.subject.fy = e.subject.y;
      })
      .on("drag", (e: { subject: SimNode; x: number; y: number }) => {
        const [x, y] = this.t.invert([e.x, e.y]);
        e.subject.fx = x;
        e.subject.fy = y;
        if (this.options.reducedMotion) {
          e.subject.x = x;
          e.subject.y = y;
          this.request();
        }
      })
      .on("end", (e: { subject: SimNode }) => {
        this.dragging = null;
        this.canvas.style.cursor = "";
        this.sim.alphaTarget(0);
        e.subject.fx = null;
        e.subject.fy = null;
      });
    select(this.canvas).call(dragging).call(this.zoom).on("dblclick.zoom", null);

    this.canvas.addEventListener("pointermove", this.onPointerMove);
    this.canvas.addEventListener("pointerleave", this.onPointerLeave);
    this.canvas.addEventListener("click", this.onClick);
    this.resizer = new ResizeObserver(() => this.resize());
    this.resizer.observe(host);
    this.resize();
  }

  /** New points and links. Points already shown keep their place; the layout
   * is stirred only when the set of points or links changed. */
  setData(nodes: GraphNode[], links: GraphLink[]): boolean {
    const signature = [
      nodes
        .map((n) => n.id)
        .sort()
        .join(","),
      links
        .map((l) => `${l.source}>${l.target}`)
        .sort()
        .join(","),
    ].join("|");
    const changed = signature !== this.signature;
    this.signature = signature;

    const ids = new Set(nodes.map((n) => n.id));
    this.allLinks = links.filter((l) => ids.has(l.source) && ids.has(l.target));
    const degree = new Map<string, number>();
    this.adjacent = new Map();
    for (const { source, target } of this.allLinks) {
      degree.set(source, (degree.get(source) ?? 0) + 1);
      degree.set(target, (degree.get(target) ?? 0) + 1);
      this.neighbours(source).add(target);
      this.neighbours(target).add(source);
    }

    const next = new Map<string, SimNode>();
    for (const n of nodes) {
      const scale = n.kind === "symbol" ? 0.6 : 1.1;
      const r = RADIUS[n.kind] + Math.sqrt(degree.get(n.id) ?? 0) * scale;
      const old = this.byId.get(n.id);
      if (old) {
        Object.assign(old, n, { r });
        next.set(n.id, old);
      } else {
        next.set(n.id, { ...n, r, x: NaN, y: NaN, a: 1, ta: 1, la: 0, tl: null });
      }
    }
    this.byId = next;
    if (this.selected && !next.has(this.selected)) this.selected = null;
    if (changed) this.rebuild();
    else this.retarget();
    return changed;
  }

  setFilters(filters: GraphFilters) {
    const localChanged =
      filters.local?.id !== this.filters.local?.id ||
      filters.local?.depth !== this.filters.local?.depth;
    const shownChanged =
      localChanged ||
      !sameSet(filters.hiddenKinds, this.filters.hiddenKinds) ||
      !sameSet(filters.hiddenStatuses, this.filters.hiddenStatuses);
    this.filters = filters;
    if (shownChanged) this.rebuild();
    else this.retarget();
  }

  setOptions(options: Partial<GraphOptions>) {
    const spacing = options.spacing !== undefined && options.spacing !== this.options.spacing;
    const occlusion =
      options.occludeRight !== undefined && options.occludeRight !== this.options.occludeRight;
    this.options = { ...this.options, ...options };
    if (spacing) {
      this.sim
        .force<ReturnType<typeof forceManyBody<SimNode>>>("charge")
        ?.strength(CHARGE * this.options.spacing);
      if (!this.options.reducedMotion) this.sim.alpha(0.4).restart();
    }
    if (occlusion) this.fitView(this.options.reducedMotion ? 0 : 500);
    this.request();
  }

  select(id: string | null) {
    if (id === this.selected) return;
    this.selected = id && this.byId.has(id) ? id : null;
    if (this.filters.local) this.rebuild();
    else this.retarget();
  }

  /** How many points and links the filters leave shown. */
  shown(): { notes: number; links: number } {
    return { notes: this.nodes.length, links: this.links.length };
  }

  /** The first shown point whose label contains `query`, for Enter in the find box. */
  firstMatch(query: string): string | null {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return this.nodes.find((n) => n.label.toLowerCase().includes(q))?.id ?? null;
  }

  /** Frame every shown point, clear of what floats over the right edge. */
  fitView(ms = 0) {
    if (!this.nodes.length || !this.width) return;
    let x0 = Infinity;
    let x1 = -Infinity;
    let y0 = Infinity;
    let y1 = -Infinity;
    for (const n of this.nodes) {
      x0 = Math.min(x0, n.x);
      x1 = Math.max(x1, n.x);
      y0 = Math.min(y0, n.y);
      y1 = Math.max(y1, n.y);
    }
    const pad = this.options.compact ? 56 : 80;
    const w = Math.max(120, this.width - this.options.occludeRight);
    const most = this.options.compact ? 1.6 : 1.8;
    const k = Math.max(
      0.3,
      Math.min(most, (w - pad * 2) / (x1 - x0 || 1), (this.height - pad * 2) / (y1 - y0 || 1)),
    );
    const target = zoomIdentity
      .translate(w / 2, this.height / 2)
      .scale(k)
      .translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    const canvas = select(this.canvas);
    if (ms && !this.options.reducedMotion) {
      canvas.transition().duration(ms).ease(easeCubicOut).call(this.zoom.transform, target);
    } else {
      canvas.call(this.zoom.transform, target);
    }
  }

  zoomBy(factor: number) {
    select(this.canvas)
      .transition()
      .duration(this.options.reducedMotion ? 0 : 280)
      .ease(easeCubicOut)
      .call(this.zoom.scaleBy, factor);
  }

  refreshColours() {
    this.palette = readPalette();
    this.request();
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.sim.stop();
    this.resizer.disconnect();
    select(this.canvas).on(".zoom", null).on(".drag", null).interrupt();
    this.canvas.removeEventListener("pointermove", this.onPointerMove);
    this.canvas.removeEventListener("pointerleave", this.onPointerLeave);
    this.canvas.removeEventListener("click", this.onClick);
    this.canvas.remove();
  }

  private neighbours(id: string): Set<string> {
    let set = this.adjacent.get(id);
    if (!set) {
      set = new Set();
      this.adjacent.set(id, set);
    }
    return set;
  }

  private around(id: string, depth: number): Set<string> {
    const seen = new Set([id]);
    let frontier = [id];
    for (let step = 0; step < depth; step++) {
      const next: string[] = [];
      for (const f of frontier) {
        for (const n of this.adjacent.get(f) ?? []) {
          if (!seen.has(n)) {
            seen.add(n);
            next.push(n);
          }
        }
      }
      frontier = next;
    }
    return seen;
  }

  private visible(): SimNode[] {
    const { hiddenKinds, hiddenStatuses, local } = this.filters;
    const scope = local ? this.around(local.id, local.depth) : null;
    return [...this.byId.values()].filter(
      (n) =>
        !hiddenKinds.has(n.kind) &&
        !(n.kind === "lesson" && n.status && hiddenStatuses.has(n.status)) &&
        (!scope || scope.has(n.id)),
    );
  }

  private rebuild() {
    this.nodes = this.visible();
    const keep = new Set(this.nodes.map((n) => n.id));
    this.links = this.allLinks
      .filter((l) => keep.has(l.source) && keep.has(l.target))
      .map((l) => ({
        source: this.byId.get(l.source) as SimNode,
        target: this.byId.get(l.target) as SimNode,
      }));

    // New points start beside a neighbour already placed, else near the middle.
    const fresh = this.nodes.filter((n) => Number.isNaN(n.x));
    const first = fresh.length === this.nodes.length;
    for (const n of fresh) {
      const anchor = [...(this.adjacent.get(n.id) ?? [])]
        .map((id) => this.byId.get(id))
        .find((m) => m && !Number.isNaN(m.x));
      const angle = Math.random() * Math.PI * 2;
      n.x = (anchor?.x ?? 0) + Math.cos(angle) * 30;
      n.y = (anchor?.y ?? 0) + Math.sin(angle) * 30;
    }

    this.sim.nodes(this.nodes);
    this.sim.force<ReturnType<typeof forceLink<SimNode, SimLink>>>("link")?.links(this.links);
    if (first || this.options.reducedMotion) {
      // Settle before the first frame so the graph opens still, not exploding:
      // fully without motion; else for at most SETTLE_MS, so a large brain
      // doesn't hold the page, and the rest settles as it draws.
      this.sim.alpha(1);
      const start = performance.now();
      let ticks = 0;
      while (ticks < 300 && (this.options.reducedMotion || performance.now() - start < SETTLE_MS)) {
        this.sim.tick();
        ticks += 1;
      }
      if (!this.options.reducedMotion) this.sim.alpha(Math.max(0.08, this.sim.alpha())).restart();
    } else {
      this.sim.alpha(0.6).restart();
    }
    this.retarget();
    if (first || !this.fitted) {
      this.fitView(0);
      this.fitted = this.width > 0;
    } else {
      this.fitView(this.options.reducedMotion ? 0 : 650);
    }
  }

  private focusId(): string | null {
    return this.hover ?? (this.options.compact ? null : this.selected);
  }

  /** What each point fades toward: the focus and its neighbours stay, the
   * rest fade; a search keeps the matches. */
  private retarget() {
    const focus = this.focusId();
    const near = focus ? this.around(focus, 1) : null;
    const query = this.filters.query.toLowerCase();
    for (const n of this.nodes) {
      let a = 1;
      if (query) a = n.label.toLowerCase().includes(query) ? 1 : FADED;
      if (near) a = near.has(n.id) ? 1 : FADED;
      n.ta = a;
      n.tl = near ? (near.has(n.id) ? 1 : 0) : query ? (a === 1 ? 1 : 0) : null;
    }
    this.request();
  }

  private pick(sx: number, sy: number): SimNode | undefined {
    const [x, y] = this.t.invert([sx, sy]);
    let best: SimNode | undefined;
    let bestD = Infinity;
    for (const n of this.nodes) {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < n.r + 6 / this.t.k && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  }

  private readonly onPointerMove = (e: PointerEvent) => {
    if (this.dragging) return;
    const box = this.canvas.getBoundingClientRect();
    const n = this.pick(e.clientX - box.left, e.clientY - box.top);
    const id = n?.id ?? null;
    if (id !== this.hover) {
      this.hover = id;
      this.retarget();
    }
    this.canvas.style.cursor = n ? "pointer" : "";
  };

  private readonly onPointerLeave = () => {
    this.hover = null;
    this.retarget();
  };

  private readonly onClick = (e: MouseEvent) => {
    const box = this.canvas.getBoundingClientRect();
    const id = this.pick(e.clientX - box.left, e.clientY - box.top)?.id ?? null;
    if (this.options.compact) {
      if (id) this.onSelect(id);
      return;
    }
    this.select(id);
    this.onSelect(this.selected);
  };

  private resize() {
    this.dpr = window.devicePixelRatio || 1;
    this.width = this.host.clientWidth;
    this.height = this.host.clientHeight;
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    if (!this.fitted && this.nodes.length && this.width) {
      this.fitView(0);
      this.fitted = true;
    }
    this.request();
  }

  private request() {
    if (!this.raf) {
      this.raf = requestAnimationFrame(() => {
        this.raf = 0;
        this.draw();
      });
    }
  }

  private draw() {
    const { ctx, dpr, t, palette: p, options } = this;
    let moving = false;
    const ease = options.reducedMotion ? 1 : 0.16;
    for (const n of this.nodes) {
      n.a += (n.ta - n.a) * ease;
      if (Math.abs(n.ta - n.a) > 0.005) moving = true;
      else n.a = n.ta;
      const early = n.kind === "strategy" || n.kind === "lesson" ? 0.6 : 1;
      const byZoom = options.compact ? 1 : smooth((t.k - options.labelAt * early) / 0.35);
      const tl = n.tl ?? byZoom;
      n.la += (tl - n.la) * ease;
      if (Math.abs(tl - n.la) > 0.005) moving = true;
      else n.la = tl;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y);

    const focus = this.focusId();
    for (const { source: s, target: d } of this.links) {
      const lit = focus !== null && (s.id === focus || d.id === focus);
      ctx.globalAlpha = Math.min(s.a, d.a) * (lit ? 0.9 : 0.55);
      ctx.strokeStyle = lit ? p.ink : p.line;
      ctx.lineWidth = (lit ? 1.4 : 1) / t.k;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(d.x, d.y);
      ctx.stroke();
    }

    for (const n of this.nodes) this.drawPoint(n, p);

    // Labels in screen space, so text stays crisp and one size at any zoom.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.setLineDash([]);
    ctx.font = FONT;
    const near = focus ? this.around(focus, 1) : null;
    const rank = (n: SimNode) =>
      n.id === focus
        ? 0
        : near?.has(n.id)
          ? 1
          : n.kind === "strategy"
            ? 2
            : n.kind === "lesson"
              ? 3
              : 4;
    const max = options.compact ? 22 : 30;
    const candidates: LabelCandidate[] = [];
    const dots = [];
    for (const n of this.nodes) {
      const [sx, sy] = t.apply([n.x, n.y]);
      if (n.a > 0.5) {
        const r = n.r * t.k + 2;
        dots.push({ id: n.id, box: { x0: sx - r, y0: sy - r, x1: sx + r, y1: sy + r } });
      }
      const alpha = n.la * Math.max(n.a, FADED) * (n.a < 0.5 ? 0.4 : 1);
      if (alpha < 0.02) continue;
      const text =
        n.id !== focus && n.label.length > max ? `${n.label.slice(0, max - 2)}…` : n.label;
      const half = ctx.measureText(text).width / 2;
      // Keep the label inside the canvas.
      const x = Math.max(half + 6, Math.min(this.width - half - 6, sx));
      candidates.push({ id: n.id, x, y: sy + n.r * t.k + 5, r: n.r, text, rank: rank(n), alpha });
    }
    const placed = placeLabels(candidates, dots, (text) => ctx.measureText(text).width);

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.lineJoin = "round";
    ctx.lineWidth = 4;
    ctx.strokeStyle = p.surface;
    for (const label of placed) {
      const n = this.byId.get(label.id);
      ctx.globalAlpha = label.alpha;
      ctx.strokeText(label.text, label.x, label.y);
      ctx.fillStyle =
        label.id === focus || (n && n.a > 0.5 && (focus || this.filters.query)) ? p.ink : p.muted;
      ctx.fillText(label.text, label.x, label.y);
    }
    ctx.globalAlpha = 1;
    if (moving) this.request();
  }

  private drawPoint(n: SimNode, p: Palette) {
    const { ctx, t } = this;
    const c = nodeColour(n, p);
    ctx.globalAlpha = n.a;
    ctx.setLineDash([]);
    if (n.id === this.selected && !this.options.compact) {
      ctx.strokeStyle = p.focus;
      ctx.lineWidth = 2 / t.k;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 4 / t.k + 1.5, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (n.kind === "proposal") {
      const s = n.r * 1.7;
      ctx.fillStyle = c;
      ctx.beginPath();
      ctx.roundRect(n.x - s / 2, n.y - s / 2, s, s, s * 0.22);
      ctx.fill();
    } else if (n.kind === "day") {
      // A ring: green when the day made money after costs, red when it lost.
      ctx.fillStyle = p.surface;
      ctx.strokeStyle = c;
      ctx.lineWidth = Math.max(1.6, n.r * 0.42);
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r - ctx.lineWidth / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (n.kind === "lesson" && n.status === "retired") {
      ctx.strokeStyle = c;
      ctx.lineWidth = 1.4;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r - 0.7, 0, Math.PI * 2);
      ctx.stroke();
    } else {
      ctx.fillStyle = n.kind === "strategy" ? p.brand : c;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
      if (n.kind === "strategy") {
        ctx.strokeStyle = c;
        ctx.lineWidth = 1 / t.k;
        ctx.stroke();
      }
    }
    if (n.id === this.hover) {
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = c;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  return a.size === b.size && [...a].every((x) => b.has(x));
}
