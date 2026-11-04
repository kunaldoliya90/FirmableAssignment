# End-to-end pipeline: (optionally) generate a dataset, run inference on observed data, then evaluate
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orggraph_dataset.config import load_config
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation
from orggraph_inference.evaluation import evaluate_predictions
from orggraph_inference.pipeline import run_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate (optional), infer on observed data, then evaluate."
    )
    parser.add_argument(
        "--dataset-dir", type=Path, default=Path("DataGenerator/datasets/FirmableAssignmentDataset")
    )
    parser.add_argument("--split", action="append", help="split(s) to infer and evaluate (default: test)")
    parser.add_argument("--output-dir", type=Path, default=None, help="where predictions/report go")
    parser.add_argument("--generate", action="store_true", help="generate the dataset first")
    parser.add_argument("--companies", type=int, default=20)
    parser.add_argument("--target-employees", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-profile", default="medium_noise")
    args = parser.parse_args(argv)
    splits = args.split or ["test"]
    output_dir = (
        args.output_dir or args.dataset_dir.parent / "_artifacts" / args.dataset_dir.name / "pipeline"
    )

    if args.generate:
        config = load_config()
        settings = GenerationSettings.from_config(
            config,
            companies=args.companies,
            target_employees=args.target_employees,
            seed=args.seed,
            noise_profile=args.noise_profile,
            output_dir=args.dataset_dir,
            overwrite=True,
        )
        result = run_generation(config, settings)
        manifest = result.manifest
        print(f"generated {manifest.employee_count:,} employees in {manifest.company_count} companies")

    predictions = output_dir / f"predictions_{'_'.join(splits)}.jsonl"
    summary = run_dataset(args.dataset_dir, predictions, splits)
    edges, employees, seconds = summary["predicted_edges"], summary["employees"], summary["elapsed_seconds"]
    print(f"inference: {edges:,} edges for {employees:,} employees in {seconds}s")

    report = evaluate_predictions(args.dataset_dir, predictions, splits)
    report_path = output_dir / f"report_{'_'.join(splits)}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    overall = report["overall"]
    for key in ("edge_precision", "edge_recall", "edge_f1", "coverage", "penalized_score"):
        print(f"  {key:<16}{overall[key]}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
