# Build the artifacts a fresh deployment starts with (split predictions and one evaluation per split), using
# the application's own services so the files are exactly what the API serves. Runs at image build time.
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from firmable.services import ServiceContainer

from Infra.Local.LocalSettings import LocalSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute predictions and evaluations for deployment.")
    parser.add_argument("--datasets-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset", default="FirmableAssignmentDataset")
    parser.add_argument(
        "--split", action="append", help="split(s) to seed (default: validation, test, challenge)"
    )
    args = parser.parse_args(argv)
    splits = args.split or ["validation", "test", "challenge"]

    settings = LocalSettings(
        environment="test",
        datasets_dir=args.datasets_dir,
        artifacts_dir=args.output_dir,
        default_dataset=args.dataset,
        log_level="WARNING",
        job_workers=1,
    )
    services = ServiceContainer.build(settings)
    try:
        for split in splits:
            started = time.perf_counter()
            services.inference.run_split_sync(args.dataset, split)
            job = services.evaluation.run(args.dataset, [split], rerun_inference=False)
            while (job := services.jobs.get(job.id)).status in ("queued", "running"):
                time.sleep(0.5)
            if job.status != "succeeded":
                print(f"evaluation of {split} failed: {job.error}", file=sys.stderr)
                return 1
            print(f"{split}: {json.dumps(job.result)} ({time.perf_counter() - started:.0f}s)")
    finally:
        services.jobs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
