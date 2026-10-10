import { expect, test } from "vitest";
import {
  type Box,
  LABEL_HEIGHT,
  type LabelCandidate,
  placeLabels,
} from "../../src/pages/brain/graph/labels";

const measure = (text: string) => text.length * 6;
const label = (id: string, x: number, y: number, rank = 4, r = 4): LabelCandidate => ({
  id,
  x,
  y,
  r,
  text: id,
  rank,
  alpha: 1,
});
const dot = (id: string, x: number, y: number, r = 5): { id: string; box: Box } => ({
  id,
  box: { x0: x - r, y0: y - r, x1: x + r, y1: y + r },
});
const ids = (placed: { id: string }[]) => placed.map((p) => p.id).sort();

test("a label that would overlap one already placed is left out", () => {
  const placed = placeLabels([label("alpha", 100, 100), label("beta", 110, 104)], [], measure);
  expect(ids(placed)).toEqual(["alpha"]);
});

test("the focused point and its neighbours label before the rest", () => {
  const placed = placeLabels(
    [label("rest", 100, 100, 4), label("near", 105, 100, 1), label("focus", 300, 300, 0)],
    [],
    measure,
  );
  expect(ids(placed)).toEqual(["focus", "near"]);
});

test("within a rank, the bigger point labels first", () => {
  const placed = placeLabels(
    [label("small", 100, 100, 2, 3), label("big", 104, 100, 2, 9)],
    [],
    measure,
  );
  expect(ids(placed)).toEqual(["big"]);
});

test("labels never cover another point, except the focused one's", () => {
  const dots = [dot("other", 100, 108), dot("own", 100, 90)];
  expect(ids(placeLabels([label("own", 100, 100, 3)], dots, measure))).toEqual([]);
  expect(ids(placeLabels([label("own", 100, 100, 0)], dots, measure))).toEqual(["own"]);
  // Its own point never blocks it.
  expect(ids(placeLabels([label("own", 100, 100, 3)], [dot("own", 100, 102)], measure))).toEqual([
    "own",
  ]);
});

test("no two placed labels overlap", () => {
  const candidates = Array.from({ length: 300 }, (_, i) =>
    label(`n${i}`, (i * 37) % 800, (i * 53) % 600, i % 5, (i % 7) + 2),
  );
  const placed = placeLabels(candidates, [], measure);
  const boxes = placed.map((p) => ({
    x0: p.x - measure(p.text) / 2,
    x1: p.x + measure(p.text) / 2,
    y0: p.y,
    y1: p.y + LABEL_HEIGHT - 2,
  }));
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i] as Box;
      const b = boxes[j] as Box;
      expect(a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1).toBe(false);
    }
  }
  expect(placed.length).toBeGreaterThan(20);
});

test("bucketing places exactly what checking every box would", () => {
  let seed = 7;
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const candidates = Array.from({ length: 1000 }, (_, i) =>
    label(`note-${i}`, random() * 1600, random() * 900, Math.floor(random() * 5), random() * 8),
  );
  const dots = candidates.map((c) => dot(c.id, c.x, c.y - 8));
  const one = placeLabels(candidates, dots, measure, 1e9); // a single bucket: every box checked
  for (const cell of [16, 64, 96, 300]) {
    expect(placeLabels(candidates, dots, measure, cell)).toEqual(one);
  }
});
