# Write reference prediction files for checking the benchmark evaluator itself
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from orggraph_dataset.pipeline.loader import DatasetReader
from orggraph_dataset.utils.jsonl import JsonlWriter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write oracle, abstain or noisy-oracle predictions to sanity-check the evaluator."
    )
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/FirmableAssignmentDataset"))
    parser.add_argument("--split", action="append", help="split(s) to cover (default: all)")
    parser.add_argument("--strategy", choices=["oracle", "abstain", "noisy_oracle"], default="noisy_oracle")
    parser.add_argument("--accuracy", type=float, default=0.8)
    parser.add_argument("--abstain-rate", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    reader = DatasetReader(args.dataset_dir)
    rng = random.Random(args.seed)
    written = 0
    with JsonlWriter(args.output) as out:
        for split in args.split or reader.splits():
            edges = list(reader.iter_ground_truth(split, "reporting_edges"))
            managers_by_company: dict[str, list[str]] = {}
            for edge in edges:
                if edge["manager_employee_id"]:
                    managers_by_company.setdefault(edge["company_id"], []).append(edge["manager_employee_id"])
            for edge in edges:
                truth = edge["manager_employee_id"]
                predicted, confidence = truth, 1.0
                if args.strategy == "abstain":
                    predicted, confidence = None, 0.0
                elif args.strategy == "noisy_oracle":
                    if rng.random() < args.abstain_rate:
                        predicted, confidence = None, 0.0
                    elif truth is None or rng.random() >= args.accuracy:
                        pool = [
                            m
                            for m in managers_by_company.get(edge["company_id"], [])
                            if m not in (truth, edge["employee_id"])
                        ]
                        predicted = rng.choice(pool) if pool else None
                        confidence = round(rng.uniform(0.2, 0.8), 3) if predicted else 0.0
                    else:
                        confidence = round(rng.uniform(0.6, 1.0), 3)
                out.write(
                    {
                        "company_id": edge["company_id"],
                        "employee_id": edge["employee_id"],
                        "predicted_manager_id": predicted,
                        "confidence": confidence,
                        "evidence": [{"type": "sanity_check", "strategy": args.strategy}],
                    }
                )
                written += 1
    print(f"wrote {written:,} {args.strategy} predictions to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
