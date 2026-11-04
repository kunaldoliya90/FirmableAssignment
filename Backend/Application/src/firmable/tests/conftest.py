# Shared fixtures: a small generated dataset and an app wired to it
from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orggraph_dataset.config import load_config
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation

from firmable.main import create_app
from Infra.Local.LocalSettings import LocalSettings

DATASET = "testds"


@pytest.fixture(scope="session")
def datasets_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("datasets")
    config = load_config()
    settings = GenerationSettings.from_config(
        config,
        companies=8,
        target_employees=1600,
        seed=5,
        output_dir=root / DATASET,
        validate_after_export=False,
    )
    run_generation(config, settings)
    return root


@pytest.fixture(scope="session")
def settings(datasets_dir: Path) -> LocalSettings:
    return LocalSettings(
        environment="test",
        datasets_dir=datasets_dir,
        artifacts_dir=datasets_dir / "_artifacts",
        default_dataset=DATASET,
        max_generation_companies=10,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def app(settings: LocalSettings) -> FastAPI:
    return create_app(settings)


@pytest.fixture(scope="session")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def company_id(client: TestClient) -> str:
    page = client.get(
        f"/api/v1/datasets/{DATASET}/companies", params={"sort": "employee_count", "descending": True}
    )
    return str(page.json()["items"][0]["company_id"])


def wait_for_job(client: TestClient, job_id: str, timeout: float = 300.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")
