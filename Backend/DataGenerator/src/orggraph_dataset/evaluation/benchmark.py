# Benchmark an inference engine's prediction file against hidden ground truth
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orggraph_dataset.evaluation.calibration import Calibration
from orggraph_dataset.evaluation.coverage_metrics import RiskCoverage
from orggraph_dataset.evaluation.edge_metrics import EdgeCounts
from orggraph_dataset.evaluation.prediction_schema import (
    Prediction,
    PredictionKey,
    load_predictions,
)
from orggraph_dataset.pipeline.loader import DatasetReader

BREAKDOWN_DIMENSIONS = (
    "industry",
    "company_size_segment",
    "org_archetype",
    "noise_profile",
    "split",
    "seniority_level",
)


class BenchmarkError(ValueError):
    pass


@dataclass
class _Accumulator:
    penalty: float
    overall: EdgeCounts = field(default_factory=EdgeCounts)
    groups: dict[str, dict[str, EdgeCounts]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(EdgeCounts))
    )

    def counts_for(self, dims: dict[str, str]) -> list[EdgeCounts]:
        return [self.overall] + [self.groups[d][v] for d, v in dims.items()]


def run_benchmark(
    dataset_dir: Path,
    predictions_path: Path,
    splits: list[str] | None = None,
    wrong_edge_penalty: float = 2.0,
    calibration_bins: int = 10,
    confidence_thresholds: list[float] | None = None,
) -> dict[str, Any]:
    reader = DatasetReader(dataset_dir)
    available = reader.splits()
    selected = splits or available
    unknown = [s for s in selected if s not in available]
    if unknown:
        raise BenchmarkError(f"split(s) {unknown} not found in {dataset_dir} (available: {available})")
    predictions = load_predictions(predictions_path)

    acc = _Accumulator(wrong_edge_penalty)
    calibration = Calibration(calibration_bins)
    risk = RiskCoverage(sorted(confidence_thresholds or [0.5, 0.7, 0.9]))
    used: set[PredictionKey] = set()
    evaluated_companies: set[str] = set()

    for split in selected:
        companies = {row["company_id"]: row for row in reader.iter_ground_truth(split, "companies")}
        evaluated_companies.update(companies)
        seniority = {
            (row["company_id"], row["employee_id"]): row["seniority_level"]
            for row in reader.iter_ground_truth(split, "canonical_roles")
        }
        company_of = {key[1]: key[0] for key in seniority}
        for edge in reader.iter_ground_truth(split, "reporting_edges"):
            key = (edge["company_id"], edge["employee_id"])
            company = companies[key[0]]
            prediction = predictions.get(key)
            if prediction is not None:
                used.add(key)
            predicted = prediction.predicted_manager_id if prediction else None
            cross = predicted is not None and company_of.get(predicted) != key[0]
            dims = _dims(company, split, seniority.get(key, "unknown"))
            outcome: bool | None = None
            for counts in acc.counts_for(dims):
                outcome = counts.record_current(
                    edge["manager_employee_id"], predicted, prediction is not None, cross
                )
            _record_confidence(calibration, risk, prediction, outcome, is_current=True)
        for person in reader.iter_ground_truth(split, "departed_employees"):
            key = (person["company_id"], person["employee_id"])
            prediction = predictions.get(key)
            if prediction is not None:
                used.add(key)
            predicted = prediction.predicted_manager_id if prediction else None
            dims = _dims(companies[key[0]], split, person["seniority_level"])
            outcome = None
            for counts in acc.counts_for(dims):
                outcome = counts.record_departed(predicted)
            _record_confidence(calibration, risk, prediction, outcome, is_current=False)

    unmatched = [k for k in predictions if k not in used]
    unmatched_in_scope = sum(1 for k in unmatched if k[0] in evaluated_companies)
    penalty = wrong_edge_penalty
    return {
        "dataset_dir": str(dataset_dir),
        "predictions_file": str(predictions_path),
        "splits": selected,
        "wrong_edge_penalty": penalty,
        "prediction_rows": len(predictions),
        "unmatched_predictions": {
            "in_evaluated_companies": unmatched_in_scope,
            "outside_evaluated_splits": len(unmatched) - unmatched_in_scope,
        },
        "overall": acc.overall.metrics(penalty),
        "calibration": calibration.to_dict(),
        "risk_coverage": risk.to_dict(),
        "breakdowns": {
            dim: {value: counts.metrics(penalty) for value, counts in sorted(acc.groups[dim].items())}
            for dim in BREAKDOWN_DIMENSIONS
        },
    }


def _dims(company: dict[str, Any], split: str, seniority: str) -> dict[str, str]:
    return {
        "industry": company["industry"],
        "company_size_segment": company["company_size_segment"],
        "org_archetype": company["org_archetype"],
        "noise_profile": company["noise_profile"],
        "split": split,
        "seniority_level": seniority,
    }


def _record_confidence(
    calibration: Calibration,
    risk: RiskCoverage,
    prediction: Prediction | None,
    outcome: bool | None,
    is_current: bool,
) -> None:
    confidence = prediction.confidence if prediction else None
    if outcome is not None and confidence is not None:
        calibration.record(confidence, outcome)
    risk.record(confidence, outcome, is_current)
