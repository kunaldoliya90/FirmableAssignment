# Benchmark metrics on hand-built ground truth with known answers
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orggraph_dataset.evaluation import PredictionFileError, load_predictions, run_benchmark
from orggraph_dataset.evaluation.calibration import Calibration
from orggraph_dataset.evaluation.edge_metrics import EdgeCounts
from orggraph_dataset.utils.jsonl import JsonlWriter

COMPANY = {
    "company_id": "c1",
    "industry": "Technology",
    "company_size_segment": "small",
    "org_archetype": "functional",
    "noise_profile": "medium_noise",
}
EDGES = [("e0", None, 0), ("e1", "e0", 1), ("e2", "e1", 2), ("e3", "e1", 2), ("e4", "e1", 2)]


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with JsonlWriter(path) as writer:
        writer.write_many(rows)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    gt = tmp_path / "ground_truth" / "test"
    (tmp_path / "observed" / "test").mkdir(parents=True)
    _write(gt / "companies.jsonl", [COMPANY])
    _write(
        gt / "canonical_roles.jsonl",
        [{"company_id": "c1", "employee_id": e, "seniority_level": "ic"} for e, _, _ in EDGES],
    )
    _write(
        gt / "reporting_edges.jsonl",
        [
            {
                "company_id": "c1",
                "employee_id": e,
                "manager_employee_id": m,
                "relationship_type": "root" if m is None else "primary",
                "hierarchy_depth": d,
            }
            for e, m, d in EDGES
        ],
    )
    _write(
        gt / "departed_employees.jsonl",
        [{"company_id": "c1", "employee_id": "gone", "seniority_level": "ic"}],
    )
    return tmp_path


def _predictions(tmp_path: Path, rows: list[tuple[str, str | None, float]]) -> Path:
    path = tmp_path / "pred.jsonl"
    _write(
        path,
        [
            {"company_id": "c1", "employee_id": e, "predicted_manager_id": m, "confidence": c, "evidence": []}
            for e, m, c in rows
        ],
    )
    return path


def test_known_metrics(dataset: Path) -> None:
    preds = _predictions(
        dataset,
        [
            ("e0", None, 0.0),
            ("e1", "e0", 0.9),
            ("e2", "e1", 0.8),
            ("e3", "e4", 0.6),
            ("gone", "e1", 0.7),
        ],
    )
    report = run_benchmark(dataset, preds, wrong_edge_penalty=2.0)
    overall = report["overall"]
    assert overall["counts"]["correct"] == 2
    assert overall["counts"]["wrong"] == 2
    assert overall["counts"]["predicted"] == 4
    assert overall["counts"]["departed_predicted"] == 1
    assert overall["counts"]["missing_predictions"] == 1
    assert overall["edge_precision"] == pytest.approx(2 / 4)
    assert overall["edge_recall"] == pytest.approx(2 / 4)
    assert overall["edge_f1"] == pytest.approx(0.5)
    assert overall["coverage"] == pytest.approx(3 / 5)
    assert overall["abstention_rate"] == pytest.approx(2 / 5)
    assert overall["penalized_score"] == pytest.approx((2 - 2 * 2) / 4)
    assert report["breakdowns"]["industry"]["Technology"]["counts"]["correct"] == 2
    assert report["calibration"]["answered_predictions"] == 4


def test_wrong_root_prediction_is_penalized(dataset: Path) -> None:
    report = run_benchmark(dataset, _predictions(dataset, [("e0", "e1", 0.5)]))
    assert report["overall"]["counts"]["wrong_on_root"] == 1
    assert report["overall"]["edge_precision"] == 0.0


def test_all_abstain(dataset: Path) -> None:
    report = run_benchmark(dataset, _predictions(dataset, [(e, None, 0.0) for e, _, _ in EDGES]))
    overall = report["overall"]
    assert overall["edge_precision"] is None
    assert overall["edge_recall"] == 0.0
    assert overall["coverage"] == 0.0 and overall["abstention_rate"] == 1.0


def test_unmatched_predictions_are_reported(dataset: Path) -> None:
    report = run_benchmark(dataset, _predictions(dataset, [("nobody", "e1", 0.4)]))
    assert report["unmatched_predictions"]["in_evaluated_companies"] == 1


def test_calibration_ece() -> None:
    cal = Calibration(bins=2)
    for conf, ok in [(0.9, True), (0.9, False), (0.2, False), (0.2, False)]:
        cal.record(conf, ok)
    result = cal.to_dict()
    assert result["expected_calibration_error"] == pytest.approx(0.3)
    assert result["brier_score"] == pytest.approx((0.01 + 0.81 + 0.04 + 0.04) / 4)


def test_edge_counts_merge() -> None:
    a, b = EdgeCounts(correct=1, predicted=2), EdgeCounts(correct=2, predicted=2)
    a.add(b)
    assert a.correct == 3 and a.predicted == 4


def test_prediction_file_errors(tmp_path: Path) -> None:
    dup = tmp_path / "dup.jsonl"
    row = {
        "company_id": "c",
        "employee_id": "e",
        "predicted_manager_id": "m",
        "confidence": 0.5,
        "evidence": [],
    }
    _write(dup, [row, row])
    with pytest.raises(PredictionFileError, match="duplicate"):
        load_predictions(dup)
    bad = tmp_path / "bad.jsonl"
    _write(bad, [{**row, "confidence": 1.5}])
    with pytest.raises(PredictionFileError, match="confidence"):
        load_predictions(bad)
    selfref = tmp_path / "self.jsonl"
    _write(selfref, [{**row, "predicted_manager_id": "e"}])
    with pytest.raises(PredictionFileError, match="themselves"):
        load_predictions(selfref)
