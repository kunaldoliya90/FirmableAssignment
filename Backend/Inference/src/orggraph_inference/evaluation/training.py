# Offline weight learning: fit the scorer's linear weights on one split, tune the abstain logit and the
# confidence threshold on another. It reads ground truth, so it lives here and never runs inside the engine;
# the engine only ever sees the resulting learned_weights.json.
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from orggraph_dataset.config import load_config
from orggraph_dataset.pipeline.loader import DatasetReader

from orggraph_inference.config import InferenceConfig, ScoringWeights
from orggraph_inference.data import ObservedDatasetReader
from orggraph_inference.evaluation import evaluate_predictions
from orggraph_inference.pipeline import InferenceEngine, run_dataset
from orggraph_inference.scoring import feature_terms, weights_from_terms

EdgeKey = tuple[str, str]
Progress = Callable[[str], None]


@dataclass
class TrainingResult:
    weights: ScoringWeights
    abstain_score: float
    confidence_threshold: float
    summary: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "abstain_score": self.abstain_score,
            "confidence_threshold": self.confidence_threshold,
            "weights": self.weights.model_dump(mode="json"),
            "training": self.summary,
        }


def load_edges(dataset_dir: Path, split: str) -> dict[EdgeKey, str | None]:
    reader = DatasetReader(dataset_dir)
    return {
        (row["company_id"], row["employee_id"]): row["manager_employee_id"]
        for row in reader.iter_ground_truth(split, "reporting_edges")
    }


# One group per employee whose true manager is among several candidates: (term rows, true index).
def collect_groups(
    engine: InferenceEngine,
    dataset_dir: Path,
    split: str,
    edges: dict[EdgeKey, str | None],
    max_companies: int | None,
    progress: Progress | None = None,
) -> tuple[list[list[dict[str, float]]], list[int]]:
    reader = ObservedDatasetReader(dataset_dir)
    companies = sorted(reader.company_ids(split))[:max_companies]
    groups: list[list[dict[str, float]]] = []
    labels: list[int] = []
    for i, cid in enumerate(companies, start=1):
        scored = engine.score_company(reader.load_company(cid, split)).scored
        for eid in sorted(scored):
            candidates = scored[eid].candidates
            ids = [c.employee_id for c in candidates]
            truth = edges.get((cid, eid))
            if truth is None or truth not in ids or len(ids) < 2:
                continue
            groups.append([feature_terms(c.features) for c in candidates])
            labels.append(ids.index(truth))
        if progress and (i % 25 == 0 or i == len(companies)):
            progress(f"collected {i}/{len(companies)} {split} companies ({len(groups)} employees)")
    return groups, labels


# Softmax over each employee's candidates (conditional logit), fitted with Adam on raw feature values.
def fit_conditional_logit(
    groups: list[list[dict[str, float]]], labels: list[int], l2: float = 1e-3, epochs: int = 300
) -> dict[str, float]:
    names = sorted({name for group in groups for row in group for name in row})
    index = {name: j for j, name in enumerate(names)}
    width = max(len(g) for g in groups)
    x = np.zeros((len(groups), width, len(names)))
    mask = np.zeros((len(groups), width), dtype=bool)
    for n, group in enumerate(groups):
        mask[n, : len(group)] = True
        for k, row in enumerate(group):
            for name, value in row.items():
                x[n, k, index[name]] = value
    target = np.zeros((len(groups), width))
    target[np.arange(len(labels)), labels] = 1.0

    w = np.zeros(len(names))
    m = np.zeros_like(w)
    v = np.zeros_like(w)
    lr, beta1, beta2 = 0.05, 0.9, 0.999
    for t in range(1, epochs + 1):
        logits = np.where(mask, x @ w, -np.inf)
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        grad = -np.einsum("nk,nkd->d", target - p, x) / len(groups) + l2 * w
        m = beta1 * m + (1 - beta1) * grad
        v = beta2 * v + (1 - beta2) * grad**2
        w -= lr * (m / (1 - beta1**t)) / (np.sqrt(v / (1 - beta2**t)) + 1e-8)
    return {name: round(float(value), 4) for name, value in zip(names, w, strict=True)}


# (confidence, correct) for every employee the graph assigns a manager, ignoring the threshold.
def decision_confidences(
    engine: InferenceEngine, dataset_dir: Path, split: str, edges: dict[EdgeKey, str | None]
) -> list[tuple[float, bool]]:
    reader = ObservedDatasetReader(dataset_dir)
    out: list[tuple[float, bool]] = []
    for cid in sorted(reader.company_ids(split)):
        graph = engine.infer_company(reader.load_company(cid, split)).graph
        for eid, decision in sorted(graph.decisions.items()):
            if decision.chosen is not None and decision.reason in ("confident", "below_threshold"):
                out.append((decision.confidence, edges.get((cid, eid)) == decision.chosen.employee_id))
    return out


# Threshold maximizing the benchmark's penalized score: (correct - penalty * wrong) / true edges.
def best_threshold(
    decisions: Iterable[tuple[float, bool]], true_edges: int, penalty: float, grid: Iterable[float]
) -> tuple[float, dict[str, float]]:
    ordered = sorted(decisions, key=lambda d: -d[0])
    best: tuple[float, dict[str, float]] | None = None
    for threshold in grid:
        kept = [ok for conf, ok in ordered if conf >= threshold]
        correct = sum(kept)
        wrong = len(kept) - correct
        metrics = {
            "precision": round(correct / len(kept), 4) if kept else 0.0,
            "recall": round(correct / true_edges, 4),
            "penalized_score": round((correct - penalty * wrong) / true_edges, 4),
        }
        if best is None or metrics["penalized_score"] > best[1]["penalized_score"]:
            best = (round(threshold, 2), metrics)
    assert best is not None
    return best


def train(
    dataset_dir: Path,
    train_split: str = "train",
    tune_split: str = "validation",
    report_split: str | None = "test",
    max_companies: int | None = 150,
    abstain_grid: tuple[float, ...] = (-4.0, -3.0, -2.0, -1.0, 0.0, 1.0),
    l2: float = 1e-3,
    epochs: int = 300,
    progress: Progress | None = None,
) -> TrainingResult:
    say = progress or (lambda _: None)
    base = InferenceConfig(weights=ScoringWeights(), abstain_score=0.6, confidence_threshold=0.55)
    penalty = load_config().dataset.evaluation.wrong_edge_penalty

    edges = load_edges(dataset_dir, train_split)
    groups, labels = collect_groups(
        InferenceEngine(base), dataset_dir, train_split, edges, max_companies, say
    )
    say(f"fitting {len(groups)} employees")
    weights = weights_from_terms(fit_conditional_logit(groups, labels, l2, epochs), base.weights)

    tune_edges = load_edges(dataset_dir, tune_split)
    true_edges = sum(1 for manager in tune_edges.values() if manager)
    grid = [t / 100 for t in range(30, 96)]
    candidates = []
    for abstain in abstain_grid:
        config = base.model_copy(
            update={"weights": weights, "abstain_score": abstain, "confidence_threshold": 0}
        )
        decisions = decision_confidences(InferenceEngine(config), dataset_dir, tune_split, tune_edges)
        threshold, metrics = best_threshold(decisions, true_edges, penalty, grid)
        say(f"abstain={abstain:+.1f}: threshold={threshold:.2f} {metrics}")
        candidates.append((metrics["penalized_score"], -abstain, abstain, threshold, metrics))
    _, _, abstain, threshold, tuned = max(candidates)

    summary: dict[str, Any] = {
        "train_split": train_split,
        "train_companies": max_companies,
        "train_employees": len(groups),
        "tune_split": tune_split,
        "tune_metrics": tuned,
        "l2": l2,
        "epochs": epochs,
    }
    if report_split:
        config = base.model_copy(
            update={"weights": weights, "abstain_score": abstain, "confidence_threshold": threshold}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.jsonl"
            run_dataset(dataset_dir, path, [report_split], engine=InferenceEngine(config))
            overall = evaluate_predictions(dataset_dir, path, [report_split])["overall"]
        summary["report_split"] = report_split
        summary["report_metrics"] = {
            k: overall[k] for k in ("edge_precision", "edge_recall", "coverage", "penalized_score")
        }
        say(f"{report_split}: {summary['report_metrics']}")
    return TrainingResult(weights, abstain, threshold, summary)


def write_learned(result: TrainingResult, path: Path) -> None:
    path.write_text(json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
