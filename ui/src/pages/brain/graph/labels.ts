// Where the graph's labels go: greedy, in priority order. A label that would
// overlap one already placed, or a point other than its own, is left out,
// never stacked. Boxes are kept in a grid of buckets so each label is checked
// only against its neighbours, not every label and point on screen.

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface LabelCandidate {
  id: string;
  /** Screen position of the label's top centre. */
  x: number;
  y: number;
  /** The point's radius on screen: bigger points label first within a rank. */
  r: number;
  text: string;
  /** 0 is the focused point (it ignores points), then its neighbours, then the rest. */
  rank: number;
  alpha: number;
}

export interface PlacedLabel {
  id: string;
  text: string;
  x: number;
  y: number;
  alpha: number;
}

export const LABEL_HEIGHT = 16;
const PAD_X = 3;

const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

class Buckets<T extends { box: Box }> {
  private readonly cells = new Map<string, T[]>();
  constructor(private readonly size: number) {}

  private keys(box: Box): string[] {
    const out: string[] = [];
    const cx0 = Math.floor(box.x0 / this.size);
    const cx1 = Math.floor(box.x1 / this.size);
    const cy0 = Math.floor(box.y0 / this.size);
    const cy1 = Math.floor(box.y1 / this.size);
    for (let cx = cx0; cx <= cx1; cx++) for (let cy = cy0; cy <= cy1; cy++) out.push(`${cx},${cy}`);
    return out;
  }

  add(item: T) {
    for (const key of this.keys(item.box)) {
      const cell = this.cells.get(key);
      if (cell) cell.push(item);
      else this.cells.set(key, [item]);
    }
  }

  some(box: Box, test: (item: T) => boolean): boolean {
    for (const key of this.keys(box)) {
      for (const item of this.cells.get(key) ?? [])
        if (overlaps(box, item.box) && test(item)) return true;
    }
    return false;
  }
}

export function placeLabels(
  candidates: LabelCandidate[],
  dots: { id: string; box: Box }[],
  measure: (text: string) => number,
  cell = 96,
): PlacedLabel[] {
  const points = new Buckets<{ id: string; box: Box }>(cell);
  for (const dot of dots) points.add(dot);
  const labels = new Buckets<{ box: Box }>(cell);

  const order = [...candidates].sort((a, b) => a.rank - b.rank || b.r - a.r);
  const placed: PlacedLabel[] = [];
  for (const c of order) {
    const half = measure(c.text) / 2 + PAD_X;
    const box = { x0: c.x - half, y0: c.y - 1, x1: c.x + half, y1: c.y + LABEL_HEIGHT - 1 };
    if (labels.some(box, () => true)) continue;
    if (c.rank > 0 && points.some(box, (dot) => dot.id !== c.id)) continue;
    labels.add({ box });
    placed.push({ id: c.id, text: c.text, x: c.x, y: c.y, alpha: c.alpha });
  }
  return placed;
}
