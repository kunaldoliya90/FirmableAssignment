// Pure state helpers for the progressively loaded org chart
import type { OrgChart, OrgEdge, OrgNode } from "@/lib/api/types";

export interface ChartState {
  nodes: Map<string, OrgNode>;
  children: Map<string, string[]>;
  confidence: Map<string, number>;
  expanded: Set<string>;
}

export function emptyState(): ChartState {
  return { nodes: new Map(), children: new Map(), confidence: new Map(), expanded: new Set() };
}

export function mergeChart(state: ChartState, chart: OrgChart): ChartState {
  const nodes = new Map(state.nodes);
  const children = new Map(state.children);
  const confidence = new Map(state.confidence);
  const expanded = new Set(state.expanded);
  const anchor = chart.nodes[0] ? nodes.get(chart.nodes[0].employee_id) : undefined;
  const offset = anchor && chart.nodes[0] ? anchor.depth - chart.nodes[0].depth : 0;
  for (const node of chart.nodes) {
    const previous = nodes.get(node.employee_id);
    nodes.set(node.employee_id, { ...node, depth: previous ? previous.depth : node.depth + offset });
  }
  const grouped = new Map<string, OrgEdge[]>();
  for (const edge of chart.edges) {
    const list = grouped.get(edge.source) ?? [];
    list.push(edge);
    grouped.set(edge.source, list);
    confidence.set(edge.target, edge.confidence);
  }
  for (const [source, edges] of grouped) {
    const merged = [...(children.get(source) ?? [])];
    for (const edge of edges) if (!merged.includes(edge.target)) merged.push(edge.target);
    children.set(source, merged);
    expanded.add(source);
  }
  return { nodes, children, confidence, expanded };
}

export function toggle(state: ChartState, id: string): ChartState {
  const expanded = new Set(state.expanded);
  if (expanded.has(id)) expanded.delete(id);
  else expanded.add(id);
  return { ...state, expanded };
}

export function needsFetch(state: ChartState, id: string): boolean {
  const node = state.nodes.get(id);
  if (!node || node.direct_reports === 0) return false;
  return (state.children.get(id)?.length ?? 0) < node.direct_reports && !state.expanded.has(id);
}

export interface VisibleNode {
  node: OrgNode;
  parentId: string | null;
  hiddenChildren: number;
}

export function visibleNodes(state: ChartState): VisibleNode[] {
  const childIds = new Set<string>();
  for (const list of state.children.values()) for (const c of list) childIds.add(c);
  const roots = [...state.nodes.keys()].filter((id) => !childIds.has(id));
  const result: VisibleNode[] = [];
  const seen = new Set<string>();
  const visit = (id: string, parentId: string | null) => {
    if (seen.has(id)) return;
    seen.add(id);
    const node = state.nodes.get(id);
    if (!node) return;
    const loaded = state.children.get(id) ?? [];
    const open = state.expanded.has(id);
    result.push({ node, parentId, hiddenChildren: open ? Math.max(node.direct_reports - loaded.length, 0) : 0 });
    if (open) for (const child of loaded) visit(child, id);
  };
  for (const root of roots) visit(root, null);
  return result;
}
