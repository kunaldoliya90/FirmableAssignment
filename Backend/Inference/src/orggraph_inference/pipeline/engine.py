# Inference pipeline: observed company data -> profiles -> candidates -> scores -> graph -> predictions
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orggraph_dataset.constants import SENIORITY_RANK
from orggraph_dataset.evaluation.prediction_schema import Prediction
from orggraph_dataset.utils.jsonl import JsonlWriter

from orggraph_inference.candidates import CandidateGenerator, choose_root
from orggraph_inference.config import InferenceConfig
from orggraph_inference.data import ObservedCompanyData, ObservedDatasetReader
from orggraph_inference.features import EmployeeProfile, ProfileBuilder
from orggraph_inference.features.profiles import ABSENCE_ONLY_DEPARTED
from orggraph_inference.graph import Decision, GraphBuilder, InferredGraph
from orggraph_inference.normalization import Vocabulary, load_vocabulary
from orggraph_inference.scoring import RelationshipScorer, ScoredEmployee


@dataclass
class CompanyInference:
    company_id: str
    profiles: dict[str, EmployeeProfile]
    graph: InferredGraph
    predictions: list[Prediction]
    stats: dict[str, Any] = field(default_factory=dict)


class InferenceEngine:
    def __init__(self, config: InferenceConfig | None = None, vocabulary: Vocabulary | None = None) -> None:
        self.config = config or InferenceConfig()
        self.vocab = vocabulary or load_vocabulary()
        self.profiles = ProfileBuilder(self.vocab, self.config)
        self.candidates = CandidateGenerator(self.config.max_candidates)
        self.scorer = RelationshipScorer(self.config)
        self.graph = GraphBuilder(self.config)

    def executive_departments(self, industry_name: str) -> dict[str, set[str]]:
        cfg = self.vocab.config
        key = self.vocab.industry_keys.get(industry_name)
        departments = cfg.industries.industries[key].departments if key else cfg.departments.departments
        overrides = cfg.industries.industries[key].executive_overrides if key else {}
        owned: dict[str, set[str]] = {}
        for dept in departments:
            role = overrides.get(dept) or cfg.departments.departments[dept].executive
            if role:
                owned.setdefault(role, set()).add(dept)
        return owned

    def infer_company(self, data: ObservedCompanyData) -> CompanyInference:
        started = time.perf_counter()
        profiles = self.profiles.build(data)
        _revive_absent_ceo(profiles)
        active = [p for p in profiles.values() if not p.departed]
        departed = {p.employee_id for p in profiles.values() if p.departed}
        root = choose_root(active)
        candidates = self.candidates.generate(profiles, root)
        exec_depts = self.executive_departments(data.company.industry)
        present = _present_ranks(active)
        scored: dict[str, ScoredEmployee] = {
            eid: self.scorer.score(
                profiles[eid], cands, exec_depts, present.get(profiles[eid].department_top_key, present[None])
            )
            for eid, cands in candidates.items()
        }
        graph = self.graph.build(
            scored,
            root.employee_id if root else None,
            departed,
            {eid: p.seniority for eid, p in profiles.items()},
        )
        predictions = [
            self._prediction(data.company.company_id, profiles[eid], graph.decisions[eid], scored.get(eid))
            for eid in profiles
        ]
        reasons = Counter(d.reason for d in graph.decisions.values())
        stats = {
            "employees": len(profiles),
            "predicted_edges": len(graph.edges),
            "abstentions": len(profiles) - len(graph.edges),
            "departed_detected": len(departed),
            "root_id": graph.root_id,
            "decision_reasons": dict(reasons),
            "reassignments": graph.reassignments,
            "cycles_broken": graph.cycles_broken,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        return CompanyInference(data.company.company_id, profiles, graph, predictions, stats)

    def _prediction(
        self, company_id: str, profile: EmployeeProfile, decision: Decision, scored: ScoredEmployee | None
    ) -> Prediction:
        manager = decision.chosen.employee_id if decision.chosen and decision.reason == "confident" else None
        evidence: list[dict[str, Any]] = [
            {
                "type": "profile",
                "observed_title": profile.title,
                "inferred_title": profile.canonical_title,
                "seniority": profile.seniority,
                "seniority_confidence": round(profile.seniority_confidence, 3),
                "job_family": profile.job_family,
                "department": profile.department_key,
                "segment": profile.segment,
                "region": profile.region,
                "observations": profile.observation_count,
                "sources": profile.sources,
            },
            {"type": "decision", "reason": decision.reason, "confidence": decision.confidence},
        ]
        if decision.reason == "departed":
            evidence.append({"type": "departed", "confidence": profile.departed_confidence})
        if decision.chosen is not None:
            evidence.append({"type": "signals", "matched": decision.chosen.features.evidence()})
        if scored is not None and scored.candidates:
            evidence.append(
                {
                    "type": "candidates",
                    "considered": len(scored.candidates),
                    "abstain_probability": round(scored.abstain_probability, 4),
                    "top": [
                        {"employee_id": c.employee_id, "probability": round(c.probability, 4)}
                        for c in scored.candidates[:3]
                    ],
                }
            )
        return Prediction(
            company_id=company_id,
            employee_id=profile.employee_id,
            predicted_manager_id=manager,
            confidence=min(max(decision.confidence, 0.0), 1.0),
            evidence=evidence,
        )


def _revive_absent_ceo(profiles: dict[str, EmployeeProfile]) -> None:
    if any(p.is_ceo and not p.departed for p in profiles.values()):
        return
    absent = [
        p
        for p in profiles.values()
        if p.is_ceo and p.departed and p.departed_confidence <= ABSENCE_ONLY_DEPARTED
    ]
    if absent:
        best = max(absent, key=lambda p: (p.observation_count, p.employee_id))
        best.departed = False


def _present_ranks(active: list[EmployeeProfile]) -> dict[str | None, list[float]]:
    leadership = {
        p.rank for p in active if p.executive_role is not None or p.rank >= SENIORITY_RANK["executive"]
    }
    by_dept: dict[str | None, set[float]] = {None: {p.rank for p in active if p.is_manager_level}}
    for p in active:
        if p.department_top_key and p.is_manager_level:
            by_dept.setdefault(p.department_top_key, set()).add(p.rank)
    return {key: sorted(ranks | leadership) for key, ranks in by_dept.items()}


def write_predictions(path: Path, predictions: Iterable[Prediction]) -> int:
    with JsonlWriter(path) as writer:
        for prediction in predictions:
            writer.write(prediction.model_dump(mode="json"))
        return writer.count


def run_dataset(
    dataset_dir: Path,
    output_path: Path,
    splits: list[str] | None = None,
    company_ids: list[str] | None = None,
    engine: InferenceEngine | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    engine = engine or InferenceEngine()
    reader = ObservedDatasetReader(dataset_dir)
    selected = splits or reader.splits()
    targets = [(split, cid) for split in selected for cid in reader.company_ids(split)]
    if company_ids is not None:
        wanted = set(company_ids)
        targets = [t for t in targets if t[1] in wanted]
    started = time.perf_counter()
    totals: Counter[str] = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".partial")
    with JsonlWriter(tmp) as writer:
        for done, (split, cid) in enumerate(targets, start=1):
            result = engine.infer_company(reader.load_company(cid, split))
            for prediction in result.predictions:
                writer.write(prediction.model_dump(mode="json"))
            totals["companies"] += 1
            totals["employees"] += result.stats["employees"]
            totals["predicted_edges"] += result.stats["predicted_edges"]
            totals["abstentions"] += result.stats["abstentions"]
            totals["departed_detected"] += result.stats["departed_detected"]
            if progress:
                progress(done, len(targets))
    tmp.replace(output_path)
    return {
        "dataset_dir": str(dataset_dir),
        "splits": selected,
        "output": str(output_path),
        **dict(totals),
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
