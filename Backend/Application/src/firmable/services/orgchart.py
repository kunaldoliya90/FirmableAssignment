# Org-chart retrieval from the inferred graph, with lazy (depth-limited, capped) expansion
from __future__ import annotations

from collections import deque

from firmable.core.errors import NotFoundError
from firmable.schemas.common import Page, paginate
from firmable.schemas.inference import OrgChart, OrgEdge, OrgNode, UnresolvedEmployee
from firmable.services.inference import CompanyView, InferenceService


class OrgChartService:
    def __init__(self, inference: InferenceService) -> None:
        self.inference = inference

    def _node(self, view: CompanyView, employee_id: str, depth: int, children_loaded: bool) -> OrgNode:
        profile = view.inference.profiles[employee_id]
        decision = view.inference.graph.decisions[employee_id]
        manager = view.edges.get(employee_id)
        return OrgNode(
            employee_id=employee_id,
            full_name=view.names.get(employee_id, employee_id),
            title=profile.canonical_title or profile.title,
            seniority=profile.seniority,
            department=profile.department_name or profile.department_key,
            manager_id=manager,
            confidence=decision.confidence if manager else 0.0,
            direct_reports=len(view.children.get(employee_id, [])),
            subtree_size=view.subtree_size.get(employee_id, 1),
            depth=depth,
            children_loaded=children_loaded,
        )

    def roots(self, view: CompanyView) -> list[str]:
        root = view.inference.graph.root_id
        tops = [eid for eid in view.names if eid not in view.edges and view.children.get(eid) and eid != root]
        tops.sort(key=lambda e: -view.subtree_size.get(e, 1))
        return ([root] if root else []) + tops

    def chart(
        self,
        dataset_id: str,
        company_id: str,
        root_id: str | None = None,
        depth: int = 2,
        max_children: int = 50,
    ) -> OrgChart:
        view = self.inference.company(dataset_id, company_id)
        if root_id is not None and root_id not in view.names:
            raise NotFoundError(f"employee '{root_id}' not found in company '{company_id}'")
        starts = [root_id] if root_id else self.roots(view)
        nodes: list[OrgNode] = []
        edges: list[OrgEdge] = []
        seen: set[str] = set()
        queue: deque[tuple[str, int]] = deque((s, 0) for s in starts)
        while queue:
            eid, level = queue.popleft()
            if eid in seen:
                continue
            seen.add(eid)
            children = view.children.get(eid, [])
            expand = level < depth
            shown = children[:max_children] if expand else []
            nodes.append(self._node(view, eid, level, expand and len(shown) == len(children)))
            for child in shown:
                edges.append(
                    OrgEdge(
                        source=eid, target=child, confidence=view.inference.graph.decisions[child].confidence
                    )
                )
                queue.append((child, level + 1))
        total = len(view.names)
        resolved = len(view.edges)
        return OrgChart(
            company_id=company_id,
            root_id=view.inference.graph.root_id,
            focus_id=root_id,
            nodes=nodes,
            edges=edges,
            resolved=resolved,
            unresolved=total - resolved - (1 if view.inference.graph.root_id else 0),
            total_employees=total,
        )

    def unresolved(
        self, dataset_id: str, company_id: str, page: int, page_size: int, reason: str | None = None
    ) -> Page[UnresolvedEmployee]:
        view = self.inference.company(dataset_id, company_id)
        rows = []
        for eid, decision in view.inference.graph.decisions.items():
            if eid in view.edges or decision.reason == "root":
                continue
            if reason and decision.reason != reason:
                continue
            profile = view.inference.profiles[eid]
            best = decision.chosen
            rows.append(
                UnresolvedEmployee(
                    employee_id=eid,
                    full_name=view.names.get(eid, eid),
                    title=profile.canonical_title or profile.title,
                    seniority=profile.seniority,
                    department=profile.department_name or profile.department_key,
                    reason=decision.reason,
                    best_candidate_id=best.employee_id if best else None,
                    best_candidate_name=view.names.get(best.employee_id) if best else None,
                    best_probability=round(best.probability, 4) if best else 0.0,
                )
            )
        rows.sort(key=lambda r: (-r.best_probability, r.full_name))
        return paginate(rows, page, page_size)
