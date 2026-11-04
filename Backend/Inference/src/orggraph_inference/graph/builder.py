# Graph construction, cycle detection and optimization
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from orggraph_dataset.validation.hierarchy_validation import find_cycles

from orggraph_inference.config import InferenceConfig
from orggraph_inference.scoring.scorer import ScoredCandidate, ScoredEmployee


@dataclass
class Decision:
    employee_id: str
    chosen: ScoredCandidate | None
    confidence: float
    reason: str


@dataclass
class InferredGraph:
    decisions: dict[str, Decision]
    root_id: str | None
    cycles_broken: int = 0
    reassignments: int = 0
    manager_seniority: dict[str, str] = field(default_factory=dict)

    @property
    def edges(self) -> dict[str, str]:
        return {
            eid: d.chosen.employee_id
            for eid, d in self.decisions.items()
            if d.chosen is not None and d.reason == "confident"
        }


class GraphBuilder:
    tie_margin = 0.1

    def __init__(self, config: InferenceConfig) -> None:
        self.config = config

    def build(
        self,
        scored: dict[str, ScoredEmployee],
        root_id: str | None,
        departed: set[str],
        seniority: dict[str, str | None],
    ) -> InferredGraph:
        choice: dict[str, int] = {eid: 0 for eid, s in scored.items() if s.candidates}
        reassignments = 0
        for _ in range(self.config.optimization_rounds):
            changed = self._balance_ties(scored, choice) + self._enforce_spans(scored, choice, seniority)
            reassignments += changed
            if not changed:
                break

        decisions: dict[str, Decision] = {}
        threshold = self.config.confidence_threshold
        for eid, s in scored.items():
            if eid in choice:
                chosen = s.candidates[choice[eid]]
                confidence = round(chosen.probability * s.profile_quality, 4)
                reason = "confident" if confidence >= threshold else "below_threshold"
                decisions[eid] = Decision(eid, chosen, confidence, reason)
            else:
                reason = "root" if eid == root_id else "no_candidates"
                decisions[eid] = Decision(eid, None, 0.0, reason)
        for eid in departed:
            decisions[eid] = Decision(eid, None, 0.0, "departed")

        graph = InferredGraph(decisions, root_id, reassignments=reassignments)
        graph.cycles_broken = self._break_cycles(graph)
        return graph

    def _balance_ties(self, scored: dict[str, ScoredEmployee], choice: dict[str, int]) -> int:
        load = Counter(scored[eid].candidates[i].employee_id for eid, i in choice.items())
        changed = 0
        for eid in sorted(choice):
            cands = scored[eid].candidates
            best = cands[0].probability
            tied = [i for i, c in enumerate(cands) if best - c.probability <= self.tie_margin * best]
            if len(tied) < 2:
                continue
            current = choice[eid]
            target = min(tied, key=lambda i: (load[cands[i].employee_id] - (i == current), i))
            if target != current:
                load[cands[current].employee_id] -= 1
                load[cands[target].employee_id] += 1
                choice[eid] = target
                changed += 1
        return changed

    def _enforce_spans(
        self, scored: dict[str, ScoredEmployee], choice: dict[str, int], seniority: dict[str, str | None]
    ) -> int:
        reports: dict[str, list[str]] = {}
        for eid, i in choice.items():
            reports.setdefault(scored[eid].candidates[i].employee_id, []).append(eid)
        changed = 0
        for manager, members in reports.items():
            cap = self.config.span_caps.get(seniority.get(manager) or "", 0)
            if not cap or len(members) <= cap:
                continue

            def margin(eid: str) -> float:
                cands = scored[eid].candidates
                i = choice[eid]
                nxt = cands[i + 1].probability if i + 1 < len(cands) else 0.0
                return cands[i].probability - nxt

            for eid in sorted(members, key=lambda e: (margin(e), e))[: len(members) - cap]:
                if choice[eid] + 1 < len(scored[eid].candidates):
                    choice[eid] += 1
                    changed += 1
        return changed

    def _break_cycles(self, graph: InferredGraph) -> int:
        broken = 0
        while True:
            parent: dict[str, str | None] = dict.fromkeys(graph.decisions)
            parent.update(graph.edges)
            cycles = find_cycles(parent)
            if not cycles:
                return broken
            for cycle in cycles:
                weakest = min(cycle, key=lambda e: graph.decisions[e].confidence)
                graph.decisions[weakest].reason = "cycle_broken"
                broken += 1
