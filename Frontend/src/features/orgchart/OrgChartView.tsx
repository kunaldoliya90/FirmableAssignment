// Interactive org chart that loads deeper levels on demand
"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, Handle, MiniMap, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, ConfidenceBadge, cx, EmptyState, ErrorState, Spinner } from "@/components/ui";
import { api } from "@/lib/api/endpoints";
import type { OrgNode } from "@/lib/api/types";
import { humanize } from "@/lib/format";

import { emptyState, mergeChart, needsFetch, toggle, visibleNodes, type ChartState } from "./graphState";
import { DEFAULT_LAYOUT, layoutTree } from "./treeLayout";

interface EmployeeNodeData extends Record<string, unknown> {
  node: OrgNode;
  expanded: boolean;
  loading: boolean;
  hiddenChildren: number;
  href: string;
  onToggle: (id: string) => void;
  onMore: (id: string) => void;
}

function EmployeeNode({ data }: NodeProps<Node<EmployeeNodeData>>) {
  const { node, expanded, loading, hiddenChildren, href, onToggle, onMore } = data;
  return (
    <div
      className={cx(
        "w-[230px] rounded-lg border bg-white px-3 py-2 text-left shadow-sm",
        node.manager_id ? "border-slate-200" : "border-brand-500",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-300" />
      <div className="flex items-start justify-between gap-2">
        <Link href={href} className="truncate text-sm font-semibold text-slate-900 hover:underline" title={node.full_name}>
          {node.full_name}
        </Link>
        {node.manager_id && <ConfidenceBadge confidence={node.confidence} />}
      </div>
      <div className="truncate text-xs text-slate-600" title={node.title ?? ""}>
        {node.title ?? "Unknown title"}
      </div>
      <div className="truncate text-[11px] text-slate-400">{node.department ? humanize(node.department) : "—"}</div>
      <div className="mt-1 flex items-center justify-between text-[11px]">
        <span className="text-slate-500">
          {node.direct_reports} reports · {node.subtree_size - 1} below
        </span>
        <span className="flex gap-1">
          {hiddenChildren > 0 && (
            <button type="button" className="font-semibold text-brand-700" onClick={() => onMore(node.employee_id)}>
              +{hiddenChildren}
            </button>
          )}
          {node.direct_reports > 0 && (
            <button type="button" className="font-semibold text-brand-700" onClick={() => onToggle(node.employee_id)} disabled={loading}>
              {loading ? "…" : expanded ? "Collapse" : "Expand"}
            </button>
          )}
        </span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-slate-300" />
    </div>
  );
}

const nodeTypes = { employee: EmployeeNode };

export function OrgChartView({ datasetId, companyId, focusId }: { datasetId: string; companyId: string; focusId?: string }) {
  const [state, setState] = useState<ChartState>(emptyState);
  const [summary, setSummary] = useState<{ resolved: number; unresolved: number; total: number } | null>(null);
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [error, setError] = useState<Error>();
  const [initialLoading, setInitialLoading] = useState(true);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    let cancelled = false;
    setState(emptyState());
    setInitialLoading(true);
    setError(undefined);
    api
      .orgChart(datasetId, companyId, focusId, 2)
      .then((chart) => {
        if (cancelled) return;
        setState((s) => mergeChart(s, chart));
        setSummary({ resolved: chart.resolved, unresolved: chart.unresolved, total: chart.total_employees });
      })
      .catch((err: Error) => !cancelled && setError(err))
      .finally(() => !cancelled && setInitialLoading(false));
    return () => {
      cancelled = true;
    };
  }, [datasetId, companyId, focusId]);

  const fetchChildren = useCallback(
    async (id: string, maxChildren: number) => {
      setLoading((l) => new Set(l).add(id));
      try {
        const chart = await api.orgChart(datasetId, companyId, id, 1, maxChildren);
        setState((s) => mergeChart(s, chart));
      } catch (err) {
        setError(err as Error);
      } finally {
        setLoading((l) => {
          const next = new Set(l);
          next.delete(id);
          return next;
        });
      }
    },
    [datasetId, companyId],
  );

  const onToggle = useCallback(
    (id: string) => {
      if (needsFetch(stateRef.current, id)) {
        void fetchChildren(id, 40);
      } else {
        setState((s) => toggle(s, id));
      }
    },
    [fetchChildren],
  );
  const onMore = useCallback((id: string) => void fetchChildren(id, 500), [fetchChildren]);

  const { nodes, edges } = useMemo(() => {
    const visible = visibleNodes(state);
    const positions = layoutTree(visible.map((v) => ({ id: v.node.employee_id, parentId: v.parentId })));
    const flowNodes: Node<EmployeeNodeData>[] = visible.map((v) => ({
      id: v.node.employee_id,
      type: "employee",
      position: positions.get(v.node.employee_id) ?? { x: 0, y: 0 },
      draggable: false,
      data: {
        node: v.node,
        expanded: state.expanded.has(v.node.employee_id),
        loading: loading.has(v.node.employee_id),
        hiddenChildren: v.hiddenChildren,
        href: `/companies/${companyId}/employees/${v.node.employee_id}`,
        onToggle,
        onMore,
      },
    }));
    const flowEdges: Edge[] = visible
      .filter((v) => v.parentId)
      .map((v) => {
        const confidence = state.confidence.get(v.node.employee_id) ?? 0;
        return {
          id: `${v.parentId}->${v.node.employee_id}`,
          source: v.parentId as string,
          target: v.node.employee_id,
          type: "smoothstep",
          style: { stroke: confidence >= 0.8 ? "#2b57d6" : "#94a3b8", strokeWidth: confidence >= 0.8 ? 1.6 : 1.1 },
        };
      });
    return { nodes: flowNodes, edges: flowEdges };
  }, [state, loading, companyId, onToggle, onMore]);

  if (error) return <ErrorState error={error} />;
  if (initialLoading) return <Spinner label="Inferring and loading the org chart… (large companies take a few seconds the first time)" />;
  if (nodes.length === 0) return <EmptyState>No confident reporting lines were inferred for this company.</EmptyState>;

  return (
    <div>
      {summary && (
        <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-slate-500">
          <span>
            {summary.resolved.toLocaleString()} of {summary.total.toLocaleString()} employees placed with a confident manager
          </span>
          <span>{summary.unresolved.toLocaleString()} unresolved (abstained)</span>
          <span>Nodes with a blue border have no confident manager.</span>
          {focusId && (
            <Link className="font-medium text-brand-700" href={`/companies/${companyId}`}>
              Show whole company
            </Link>
          )}
        </div>
      )}
      <div className="h-[640px] rounded-xl border border-slate-200 bg-slate-50">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
          minZoom={0.05}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          onlyRenderVisibleElements
          defaultEdgeOptions={{ type: "smoothstep" }}
          nodeOrigin={[0.5, 0]}
        >
          <Background gap={24} color="#e2e8f0" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeStrokeWidth={2} />
        </ReactFlow>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Layout width per node: {DEFAULT_LAYOUT.nodeWidth}px. Expand loads reports on demand; “+N” loads the remaining reports.
      </p>
      <div className="mt-1">
        <Button variant="ghost" onClick={() => setState((s) => ({ ...s, expanded: new Set() }))}>
          Collapse all
        </Button>
      </div>
    </div>
  );
}
