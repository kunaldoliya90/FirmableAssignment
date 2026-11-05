# Inference orchestration: per-company inference (cached) and split-level prediction runs
from __future__ import annotations

import json
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any

from orggraph_dataset.schemas import EmployeeObservation, ObservedCompany
from orggraph_inference.config import InferenceConfig
from orggraph_inference.data import ObservedDataError
from orggraph_inference.pipeline import CompanyInference, InferenceEngine, run_dataset

from firmable.core.errors import ConflictError, NotFoundError
from firmable.core.jobs import Job, JobContext, JobManager
from firmable.services.datasets import DatasetService
from Infra.Common.BaseSettings import CommonSettings


@dataclass
class CompanyView:
    dataset_id: str
    split: str
    company: ObservedCompany
    inference: CompanyInference
    names: dict[str, str]
    employment_types: dict[str, str]
    observations: dict[str, list[EmployeeObservation]]
    children: dict[str, list[str]] = field(default_factory=dict)
    subtree_size: dict[str, int] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.edges = self.inference.graph.edges
        children: dict[str, list[str]] = defaultdict(list)
        for employee, manager in self.edges.items():
            children[manager].append(employee)
        sizes: dict[str, int] = {}

        def size(node: str) -> int:
            stack, order = [node], []
            while stack:
                current = stack.pop()
                order.append(current)
                stack.extend(children.get(current, []))
            for current in reversed(order):
                sizes[current] = 1 + sum(sizes[c] for c in children.get(current, []))
            return sizes[node]

        for node in self.names:
            if node not in sizes:
                size(node)
        profiles = self.inference.profiles

        def order_key(eid: str) -> tuple[float, int, str]:
            return (-profiles[eid].rank, -sizes.get(eid, 1), self.names.get(eid, ""))

        self.children = {m: sorted(c, key=order_key) for m, c in children.items()}
        self.subtree_size = sizes


class InferenceService:
    def __init__(self, settings: CommonSettings, datasets: DatasetService, jobs: JobManager) -> None:
        self.settings = settings
        self.datasets = datasets
        self.jobs = jobs
        self.config = InferenceConfig(max_candidates=settings.inference.max_candidates)
        if settings.inference.confidence_threshold is not None:
            self.config = self.config.model_copy(
                update={"confidence_threshold": settings.inference.confidence_threshold}
            )
        self._engine: InferenceEngine | None = None
        self._engine_lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], CompanyView] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._company_locks: dict[tuple[str, str], threading.Lock] = defaultdict(threading.Lock)

    @property
    def engine(self) -> InferenceEngine:
        with self._engine_lock:
            if self._engine is None:
                self._engine = InferenceEngine(self.config)
            return self._engine

    def cached(self, dataset_id: str, company_id: str) -> CompanyView | None:
        with self._cache_lock:
            return self._cache.get((dataset_id, company_id))

    def company(self, dataset_id: str, company_id: str, refresh: bool = False) -> CompanyView:
        key = (dataset_id, company_id)
        if not refresh and (view := self.cached(*key)) is not None:
            with self._cache_lock:
                self._cache.move_to_end(key)
            return view
        with self._company_locks[key]:
            if not refresh and (view := self.cached(*key)) is not None:
                return view
            reader = self.datasets.reader(dataset_id)
            split = reader.split_of(company_id)
            if split is None:
                raise NotFoundError(f"company '{company_id}' not found in dataset '{dataset_id}'")
            try:
                data = reader.load_company(company_id, split)
            except ObservedDataError as exc:
                raise NotFoundError(str(exc)) from exc
            result = self.engine.infer_company(data)
            observations: dict[str, list[EmployeeObservation]] = defaultdict(list)
            for obs in data.observations:
                observations[obs.employee_id].append(obs)
            view = CompanyView(
                dataset_id=dataset_id,
                split=split,
                company=data.company,
                inference=result,
                names={e.employee_id: e.full_name for e in data.employees},
                employment_types={e.employee_id: e.employment_type.value for e in data.employees},
                observations=dict(observations),
            )
        with self._cache_lock:
            self._cache[key] = view
            self._cache.move_to_end(key)
            while len(self._cache) > self.settings.inference.company_cache_size:
                self._cache.popitem(last=False)
        return view

    def invalidate(self, dataset_id: str) -> None:
        with self._cache_lock:
            for key in [k for k in self._cache if k[0] == dataset_id]:
                del self._cache[key]

    def run_splits(self, dataset_id: str, splits: list[str]) -> Job:
        self.datasets.dataset_dir(dataset_id)
        for split in splits:
            self.datasets.check_split(dataset_id, split)
        key = f"{dataset_id}:{','.join(sorted(splits))}"
        if self.jobs.active("inference", key):
            raise ConflictError(f"inference for {splits} is already running")

        def work(ctx: JobContext) -> dict[str, Any]:
            summaries = {}
            for i, split in enumerate(splits):
                summaries[split] = self.run_split_sync(dataset_id, split, ctx, i, len(splits))
            return {"dataset_id": dataset_id, "splits": summaries}

        return self.jobs.submit("inference", {"key": key, "dataset_id": dataset_id, "splits": splits}, work)

    def run_split_sync(
        self, dataset_id: str, split: str, ctx: JobContext | None = None, index: int = 0, count: int = 1
    ) -> dict[str, Any]:
        dataset_dir = self.datasets.dataset_dir(dataset_id)
        output = self.datasets.predictions_path(dataset_id, split)

        def progress(done: int, total: int) -> None:
            if ctx is not None:
                ctx.progress((index + done / total) / count, f"{split}: inferred {done}/{total} companies")

        summary = run_dataset(dataset_dir, output, [split], engine=self.engine, progress=progress)
        summary["confidence_threshold"] = self.config.confidence_threshold
        output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def runs(self, dataset_id: str) -> list[dict[str, Any]]:
        self.datasets.dataset_dir(dataset_id)
        runs = []
        for split in self.datasets.inferred_splits(dataset_id):
            path = self.datasets.predictions_path(dataset_id, split)
            summary_path = path.with_suffix(".summary.json")
            summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
            runs.append({"split": split, "predictions_file": str(path), "summary": summary})
        return runs
