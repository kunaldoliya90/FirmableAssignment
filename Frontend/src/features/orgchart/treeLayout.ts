// Tidy top-down tree layout; parents centred over visible children
export interface LayoutInput {
  id: string;
  parentId: string | null;
}

export interface Position {
  x: number;
  y: number;
}

export interface LayoutOptions {
  nodeWidth: number;
  nodeHeight: number;
  horizontalGap: number;
  verticalGap: number;
}

export const DEFAULT_LAYOUT: LayoutOptions = { nodeWidth: 230, nodeHeight: 84, horizontalGap: 24, verticalGap: 70 };

export function layoutTree(nodes: LayoutInput[], options: LayoutOptions = DEFAULT_LAYOUT): Map<string, Position> {
  const ids = new Set(nodes.map((n) => n.id));
  const children = new Map<string, string[]>();
  const roots: string[] = [];
  for (const node of nodes) {
    if (node.parentId && ids.has(node.parentId) && node.parentId !== node.id) {
      const list = children.get(node.parentId) ?? [];
      list.push(node.id);
      children.set(node.parentId, list);
    } else {
      roots.push(node.id);
    }
  }

  const positions = new Map<string, Position>();
  const step = options.nodeWidth + options.horizontalGap;
  const rowHeight = options.nodeHeight + options.verticalGap;
  let nextLeaf = 0;
  const visiting = new Set<string>();

  const place = (id: string, depth: number): number => {
    if (visiting.has(id)) return nextLeaf * step;
    visiting.add(id);
    const kids = children.get(id) ?? [];
    let x: number;
    if (kids.length === 0) {
      x = nextLeaf * step;
      nextLeaf += 1;
    } else {
      const xs = kids.map((kid) => place(kid, depth + 1));
      x = (Math.min(...xs) + Math.max(...xs)) / 2;
    }
    positions.set(id, { x, y: depth * rowHeight });
    return x;
  };

  for (const root of roots) {
    place(root, 0);
    nextLeaf += 0.5;
  }
  return positions;
}
