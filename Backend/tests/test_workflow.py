# Cross-component integration: DataGenerator -> Inference -> evaluation -> FastAPI, on one dataset
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from firmable.main import create_app
from orggraph_dataset.config import load_config
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation
from orggraph_dataset.validation import validate_dataset_dir
from orggraph_inference.evaluation import evaluate_predictions
from orggraph_inference.pipeline import run_dataset

from Infra.Local.LocalSettings import LocalSettings

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("workflow") / "wf"
    config = load_config()
    settings = GenerationSettings.from_config(
        config, companies=6, target_employees=600, seed=77, output_dir=root
    )
    result = run_generation(config, settings)
    assert result.validation is not None and result.validation.ok
    return root


def test_generated_dataset_validates_after_reload(dataset: Path) -> None:
    report = validate_dataset_dir(dataset, load_config(), min_companies=6, min_total_employees=600)
    assert report.ok, report.summary_lines()
    assert report.issue_counts.get("leakage.forbidden_field", 0) == 0


def test_inference_on_observed_copy_then_evaluation(dataset: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    shutil.copytree(dataset / "observed", runtime / "observed")
    predictions = tmp_path / "predictions.jsonl"
    summary = run_dataset(runtime, predictions)
    assert summary["employees"] >= 600 and summary["predicted_edges"] > 0

    report = evaluate_predictions(dataset, predictions)
    overall = report["overall"]
    assert overall["edge_precision"] > 0.75
    assert overall["counts"]["missing_predictions"] == 0
    assert overall["penalized_score"] > 0


def test_api_serves_the_same_inference(dataset: Path, tmp_path: Path) -> None:
    datasets_dir = dataset.parent
    settings = LocalSettings(
        environment="test",
        datasets_dir=datasets_dir,
        artifacts_dir=tmp_path / "artifacts",
        log_level="WARNING",
    )
    client = TestClient(create_app(settings))
    companies = client.get(f"/api/v1/datasets/{dataset.name}/companies").json()["items"]
    company_id = companies[0]["company_id"]

    run_dataset(dataset, tmp_path / "direct.jsonl", company_ids=[company_id])
    direct = {
        row["employee_id"]: row["predicted_manager_id"]
        for row in map(json.loads, (tmp_path / "direct.jsonl").read_text(encoding="utf-8").splitlines())
    }
    employees = client.get(
        f"/api/v1/datasets/{dataset.name}/companies/{company_id}/employees", params={"page_size": 500}
    ).json()
    via_api = {e["employee_id"]: e["predicted_manager_id"] for e in employees["items"]}
    assert via_api == {k: v for k, v in direct.items() if k in via_api}
    assert len(via_api) == min(len(direct), 500)
