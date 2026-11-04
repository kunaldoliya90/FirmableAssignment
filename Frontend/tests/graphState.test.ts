// Org-chart state merging and visibility
import { describe, expect, it } from "vitest";

import { emptyState, mergeChart, needsFetch, toggle, visibleNodes } from "@/features/orgchart/graphState";
import type { OrgChart, OrgNode } from "@/lib/api/types";

function node(id: string, manager: string | null, reports: number, depth: number): OrgNode {
  return {
    employee_id: id,
    full_name: id.toUpperCase(),
    title: null,
    seniority: null,
    department: null,
    manager_id: manager,
    confidence: 0.9,
    direct_reports: reports,
    subtree_size: reports + 1,
    depth,
    children_loaded: false,
  };
}

function chart(nodes: OrgNode[]): OrgChart {
  return {
    company_id: "c",
    root_id: "ceo",
    focus_id: null,
    nodes,
    edges: nodes.filter((n) => n.manager_id).map((n) => ({ source: n.manager_id!, target: n.employee_id, confidence: n.confidence })),
    resolved: 0,
    unresolved: 0,
    total_employees: nodes.length,
  };
}

describe("org chart state", () => {
  it("merges partial charts and expands lazily", () => {
    let state = mergeChart(emptyState(), chart([node("ceo", null, 2, 0), node("cto", "ceo", 3, 1), node("cfo", "ceo", 0, 1)]));
    expect(visibleNodes(state).map((v) => v.node.employee_id)).toEqual(["ceo", "cto", "cfo"]);
    expect(needsFetch(state, "cto")).toBe(true);
    expect(needsFetch(state, "cfo")).toBe(false);

    state = mergeChart(state, chart([node("cto", "ceo", 3, 0), node("e1", "cto", 0, 1), node("e2", "cto", 0, 1)]));
    const visible = visibleNodes(state);
    expect(visible.map((v) => v.node.employee_id)).toEqual(["ceo", "cto", "e1", "e2", "cfo"]);
    expect(visible.find((v) => v.node.employee_id === "cto")?.hiddenChildren).toBe(1);
    expect(state.nodes.get("cto")?.depth).toBe(1);

    state = toggle(state, "cto");
    expect(visibleNodes(state).map((v) => v.node.employee_id)).toEqual(["ceo", "cto", "cfo"]);
    expect(needsFetch(state, "cto")).toBe(true);
  });
});
