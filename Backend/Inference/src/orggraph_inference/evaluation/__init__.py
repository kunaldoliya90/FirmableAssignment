# Evaluation of finished prediction files against hidden ground truth
from __future__ import annotations

from pathlib import Path
from typing import Any

from orggraph_dataset.config import OrgGraphConfig, load_config
from orggraph_dataset.evaluation import run_benchmark


def evaluate_predictions(
    dataset_dir: Path,
    predictions_path: Path,
    splits: list[str] | None = None,
    config: OrgGraphConfig | None = None,
) -> dict[str, Any]:
    if not predictions_path.is_file():
        raise FileNotFoundError(f"predictions file not found (has inference finished?): {predictions_path}")
    evaluation = (config or load_config()).dataset.evaluation
    return run_benchmark(
        dataset_dir,
        predictions_path,
        splits=splits,
        wrong_edge_penalty=evaluation.wrong_edge_penalty,
        calibration_bins=evaluation.calibration_bins,
        confidence_thresholds=evaluation.confidence_thresholds,
    )


__all__ = ["evaluate_predictions"]
