// Tree layout positions and spacing
import { describe, expect, it } from "vitest";

import { DEFAULT_LAYOUT, layoutTree } from "@/features/orgchart/treeLayout";

describe("layoutTree", () => {
  it("centres parents over their children and stacks levels", () => {
    const positions = layoutTree([
      { id: "ceo", parentId: null },
      { id: "a", parentId: "ceo" },
      { id: "b", parentId: "ceo" },
      { id: "a1", parentId: "a" },
    ]);
    const ceo = positions.get("ceo")!;
    const a = positions.get("a")!;
    const b = positions.get("b")!;
    expect(ceo.y).toBe(0);
    expect(a.y).toBe(DEFAULT_LAYOUT.nodeHeight + DEFAULT_LAYOUT.verticalGap);
    expect(ceo.x).toBe((a.x + b.x) / 2);
    expect(positions.get("a1")!.x).toBe(a.x);
  });

  it("never overlaps siblings and handles multiple roots and unknown parents", () => {
    const nodes = [
      { id: "r1", parentId: null },
      { id: "r2", parentId: "missing" },
      ...Array.from({ length: 5 }, (_, i) => ({ id: `c${i}`, parentId: "r1" })),
    ];
    const positions = layoutTree(nodes);
    const xs = Array.from({ length: 5 }, (_, i) => positions.get(`c${i}`)!.x).sort((p, q) => p - q);
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(DEFAULT_LAYOUT.nodeWidth);
    }
    expect(positions.get("r2")!.y).toBe(0);
    expect(positions.get("r2")!.x).toBeGreaterThan(Math.max(...xs));
  });

  it("ignores self-references", () => {
    const positions = layoutTree([{ id: "x", parentId: "x" }]);
    expect(positions.get("x")).toEqual({ x: 0, y: 0 });
  });
});
