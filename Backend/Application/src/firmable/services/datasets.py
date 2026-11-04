# Dataset discovery, metadata, generation and validation (delegates to the DataGenerator package)
from __future__ import annotations

import builtins
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from orggraph_dataset.config import ConfigError, OrgGraphConfig, load_config
from orggraph_dataset.constants import MANIFEST_FILE, METADATA_DIR, SPLITS
from orggraph_dataset.pipeline.orchestrator import GenerationSettings, run_generation
from orggraph_dataset.utils.jsonl import read_json
from orggraph_dataset.validation import validate_dataset_dir
from orggraph_inference.data import ObservedDatasetReader

from firmable.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from firmable.core.jobs import Job, JobContext, JobManager
from firmable.schemas.datasets import DatasetDetail, DatasetSummary, GenerateDatasetRequest, NoiseProfileInfo
from Infra.Common.BaseSettings import CommonSettings

_DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class DatasetService:
    def __init__(self, settings: CommonSettings, jobs: JobManager) -> None:
        self.settings = settings
        self.jobs = jobs
        self._config: OrgGraphConfig | None = None
        self._readers: dict[str, ObservedDatasetReader] = {}
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str], None]] = []

    def on_invalidate(self, listener: Callable[[str], None]) -> None:
        self._listeners.append(listener)

    @property
    def config(self) -> OrgGraphConfig:
        if self._config is None:
            self._config = load_config(self.settings.generator_config_dir)
        return self._config

    def dataset_dir(self, dataset_id: str) -> Path:
        if not _DATASET_ID.match(dataset_id):
            raise NotFoundError(f"dataset '{dataset_id}' not found")
        path = self.settings.datasets_dir / dataset_id
        if not (path / METADATA_DIR / MANIFEST_FILE).is_file():
            raise NotFoundError(f"dataset '{dataset_id}' not found")
        return path

    def artifacts_dir(self, dataset_id: str) -> Path:
        return self.settings.artifacts_dir / dataset_id

    def predictions_path(self, dataset_id: str, split: str) -> Path:
        return self.artifacts_dir(dataset_id) / "predictions" / f"{split}.jsonl"

    def reader(self, dataset_id: str) -> ObservedDatasetReader:
        path = self.dataset_dir(dataset_id)
        with self._lock:
            reader = self._readers.get(dataset_id)
            if reader is None:
                reader = ObservedDatasetReader(path)
                self._readers[dataset_id] = reader
            return reader

    def invalidate(self, dataset_id: str) -> None:
        with self._lock:
            self._readers.pop(dataset_id, None)
        for listener in self._listeners:
            listener(dataset_id)

    def check_split(self, dataset_id: str, split: str) -> None:
        if split not in self.reader(dataset_id).splits():
            raise NotFoundError(f"split '{split}' not found in dataset '{dataset_id}'")

    def manifest(self, dataset_id: str) -> dict[str, Any]:
        manifest: dict[str, Any] = read_json(self.dataset_dir(dataset_id) / METADATA_DIR / MANIFEST_FILE)
        return manifest

    def inferred_splits(self, dataset_id: str) -> list[str]:
        return [s for s in SPLITS if self.predictions_path(dataset_id, s).is_file()]

    def _summary_fields(self, dataset_id: str) -> dict[str, Any]:
        m = self.manifest(dataset_id)
        profile = m["noise_profile"]
        return {
            "dataset_id": dataset_id,
            "company_count": m["company_count"],
            "employee_count": m["employee_count"],
            "observation_count": m["observation_count"],
            "departed_employee_count": m["departed_employee_count"],
            "generation_timestamp": m["generation_timestamp"],
            "random_seed": m["random_seed"],
            "noise_profile": profile["base_profile"],
            "challenge_noise_profile": profile["challenge_profile"],
            "split_distribution": m["split_distribution"],
            "inferred_splits": self.inferred_splits(dataset_id),
        }

    def list(self) -> list[DatasetSummary]:
        root = self.settings.datasets_dir
        if not root.is_dir():
            return []
        summaries = []
        for path in sorted(root.iterdir()):
            if path.name.startswith(("_", ".")) or not (path / METADATA_DIR / MANIFEST_FILE).is_file():
                continue
            summaries.append(DatasetSummary(**self._summary_fields(path.name)))
        return summaries

    def detail(self, dataset_id: str) -> DatasetDetail:
        m = self.manifest(dataset_id)
        return DatasetDetail(
            **self._summary_fields(dataset_id),
            dataset_version=m["dataset_version"],
            schema_version=m["schema_version"],
            industry_distribution=m["industry_distribution"],
            company_size_distribution=m["company_size_distribution"],
            archetype_distribution=m["archetype_distribution"],
            noise_profile_distribution=m["noise_profile_distribution"],
        )

    def noise_profiles(self) -> builtins.list[NoiseProfileInfo]:
        return [
            NoiseProfileInfo(
                name=name, description=p.description, parameters=p.model_dump(exclude={"description"})
            )
            for name, p in self.config.noise.profiles.items()
        ]

    def generate(self, request: GenerateDatasetRequest) -> Job:
        if not self.settings.allow_dataset_generation:
            raise ForbiddenError("dataset generation is disabled in this environment")
        if request.companies > self.settings.max_generation_companies:
            raise UnprocessableError(f"companies must be <= {self.settings.max_generation_companies}")
        output = self.settings.datasets_dir / request.dataset_id
        if (output / METADATA_DIR / MANIFEST_FILE).exists() and not request.overwrite:
            raise ConflictError(
                f"dataset '{request.dataset_id}' already exists; set overwrite=true to replace it"
            )
        if self.jobs.active("generate_dataset", request.dataset_id):
            raise ConflictError(f"dataset '{request.dataset_id}' is already being generated")
        try:
            settings = GenerationSettings.from_config(
                self.config,
                companies=request.companies,
                min_employees_per_company=request.min_employees_per_company,
                target_employees=request.target_employees,
                seed=request.seed,
                noise_profile=request.noise_profile,
                challenge_noise_profile=request.challenge_noise_profile,
                output_dir=output,
                overwrite=request.overwrite,
            )
            from orggraph_dataset.pipeline.orchestrator import plan_dataset

            plan_dataset(self.config, settings)
        except ConfigError as exc:
            raise UnprocessableError(str(exc)) from exc

        def work(ctx: JobContext) -> dict[str, Any]:
            def progress(done: int, total: int, employees: int) -> None:
                ctx.progress(
                    done / total * 0.8, f"generated {done}/{total} companies ({employees:,} employees)"
                )

            result = run_generation(self.config, settings, progress=progress)
            self.invalidate(request.dataset_id)
            return {
                "dataset_id": request.dataset_id,
                "companies": result.manifest.company_count,
                "employees": result.manifest.employee_count,
                "observations": result.manifest.observation_count,
                "validation_passed": result.validation.ok if result.validation else None,
            }

        return self.jobs.submit("generate_dataset", {"key": request.dataset_id, **request.model_dump()}, work)

    def validate(self, dataset_id: str) -> Job:
        path = self.dataset_dir(dataset_id)

        def work(ctx: JobContext) -> dict[str, Any]:
            ctx.progress(0.05, "validating")
            report = validate_dataset_dir(path, self.config)
            return {
                "ok": report.ok,
                "error_count": report.error_count,
                "checks": sum(report.checks.values()),
                "leakage_checks": sum(v for k, v in report.checks.items() if k.startswith("leakage.")),
                "issue_counts": dict(report.issue_counts),
                "stats": report.stats,
                "issues": [str(i) for i in report.issues[:50]],
            }

        return self.jobs.submit("validate_dataset", {"key": dataset_id, "dataset_id": dataset_id}, work)
