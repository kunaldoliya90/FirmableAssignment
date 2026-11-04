# `orggraph-infer`: run inference on observed data, then (separately) evaluate the finished file
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="orggraph-infer", no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False
)

DatasetOpt = Annotated[Path, typer.Option(help="Dataset directory (only observed/ is read).")]


@app.command(help="Infer reporting lines from observed data and write predictions.")
def run(
    output: Annotated[Path, typer.Option(help="Prediction JSONL to write.")],
    dataset_dir: DatasetOpt = Path("DataGenerator/datasets/FirmableAssignmentDataset"),
    split: Annotated[list[str] | None, typer.Option(help="Split(s) to infer (default: all).")] = None,
    company: Annotated[list[str] | None, typer.Option(help="Restrict to these company IDs.")] = None,
    confidence_threshold: Annotated[float | None, typer.Option(help="Abstain below this confidence.")] = None,
) -> None:
    from orggraph_inference.config import InferenceConfig
    from orggraph_inference.pipeline import InferenceEngine, run_dataset

    config = InferenceConfig()
    if confidence_threshold is not None:
        config = config.model_copy(update={"confidence_threshold": confidence_threshold})

    def progress(done: int, total: int) -> None:
        if done == total or done % 25 == 0:
            typer.echo(f"  inferred {done}/{total} companies", err=True)

    summary = run_dataset(dataset_dir, output, split, company, InferenceEngine(config), progress)
    typer.echo(json.dumps(summary, indent=2))


@app.command(help="Score a finished prediction file against ground truth.")
def evaluate(
    predictions: Annotated[Path, typer.Option(help="Finished prediction JSONL.")],
    dataset_dir: DatasetOpt = Path("DataGenerator/datasets/FirmableAssignmentDataset"),
    split: Annotated[list[str] | None, typer.Option(help="Split(s) to evaluate.")] = None,
    output: Annotated[Path | None, typer.Option(help="Write the full report here.")] = None,
) -> None:
    from orggraph_inference.evaluation import evaluate_predictions

    report = evaluate_predictions(dataset_dir, predictions, split)
    if output:
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    overall = report["overall"]
    for key in ("edge_precision", "edge_recall", "edge_f1", "coverage", "abstention_rate", "penalized_score"):
        typer.echo(f"{key:<20}{overall[key]}")
    typer.echo(f"{'ECE':<20}{report['calibration']['expected_calibration_error']}")


if __name__ == "__main__":
    app()
