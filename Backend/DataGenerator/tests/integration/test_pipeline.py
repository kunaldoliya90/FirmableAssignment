# Generate -> validate -> export -> reload -> validate again, through the API and the CLI
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from orggraph_dataset.cli import app
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.pipeline.loader import DatasetReader
from orggraph_dataset.pipeline.orchestrator import GenerationResult
from orggraph_dataset.validation import validate_dataset_dir
from orggraph_dataset.validation.dataset_validation import records_from_chunk
from orggraph_dataset.validation.report import ValidationReport
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_small_dataset_generated_and_validated(small_dataset: GenerationResult) -> None:
    assert small_dataset.validation is not None and small_dataset.validation.ok
    m = small_dataset.manifest
    assert m.company_count == 16
    assert m.employee_count >= 1600
    assert m.observation_count > m.employee_count


def test_reload_and_validate_again(small_dataset: GenerationResult, config: OrgGraphConfig) -> None:
    report = validate_dataset_dir(
        small_dataset.output_dir, config, min_companies=16, min_total_employees=1600
    )
    assert report.ok, report.summary_lines()
    assert report.stats["employees"] == small_dataset.manifest.employee_count
    reader = DatasetReader(small_dataset.output_dir)
    parse_report = ValidationReport()
    reloaded = [
        records_from_chunk(c, parse_report) for s in reader.splits() for c in reader.iter_company_chunks(s)
    ]
    assert all(r is not None for r in reloaded) and parse_report.ok
    assert sum(len(r.employees) for r in reloaded if r) == small_dataset.manifest.employee_count


def test_cli_end_to_end(tmp_path: Path) -> None:
    out = tmp_path / "cli_ds"
    result = runner.invoke(
        app,
        [
            "generate",
            "--companies",
            "5",
            "--target-employees",
            "500",
            "--seed",
            "3",
            "--noise-profile",
            "low_noise",
            "--output-dir",
            str(out),
            "--log-level",
            "WARNING",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "validation          passed" in result.output

    result = runner.invoke(app, ["validate", "--dataset-dir", str(out), "--min-companies", "5"])
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output

    preds = tmp_path / "oracle.jsonl"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "make_sanity_predictions.py"),
            "--dataset-dir",
            str(out),
            "--strategy",
            "oracle",
            "--output",
            str(preds),
        ],
        check=True,
        capture_output=True,
    )
    report = tmp_path / "bench.json"
    result = runner.invoke(
        app, ["benchmark", "--dataset-dir", str(out), "--predictions", str(preds), "--output", str(report)]
    )
    assert result.exit_code == 0, result.output
    assert "edge_precision          1.0" in result.output
    assert report.exists()

    result = runner.invoke(
        app, ["generate", "--companies", "5", "--target-employees", "500", "--output-dir", str(out)]
    )
    assert result.exit_code == 2 and "--overwrite" in result.output


def test_cli_reports_config_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate", "--companies", "10", "--target-employees", "500", "--output-dir", str(tmp_path / "x")],
    )
    assert result.exit_code == 2
    assert "conflicts" in result.output
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0 and "medium_noise" in result.output
    result = runner.invoke(app, ["config", "--section", "sources"])
    assert result.exit_code == 0 and "hr_export" in result.output


def test_validate_fails_on_missing_dataset(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--dataset-dir", str(tmp_path)])
    assert result.exit_code == 1
