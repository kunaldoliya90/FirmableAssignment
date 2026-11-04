# Evaluation against hidden ground truth
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orggraph_dataset.constants import GROUND_TRUTH_DIR, GROUND_TRUTH_FILES
from orggraph_dataset.evaluation.calibration import Calibration
from orggraph_dataset.evaluation.edge_metrics import EdgeCounts
from orggraph_dataset.utils.jsonl import JsonlWriter, iter_jsonl
from orggraph_inference.evaluation import evaluate_predictions

from firmable.core.errors import ConflictError, NotFoundError
from firmable.core.jobs import Job, JobContext, JobManager
from firmable.schemas.evaluation import CompanyEvaluation, EvaluationReport, EvaluationSummary
from firmable.services.datasets import DatasetService
from firmable.services.inference import InferenceService


class EvaluationService:
    def __init__(self, datasets: DatasetService, inference: InferenceService, jobs: JobManager) -> None:
        self.datasets = datasets
        self.inference = inference
        self.jobs = jobs

    def _dir(self, dataset_id: str) -> Path:
        return self.datasets.artifacts_dir(dataset_id) / "evaluations"

    def run(self, dataset_id: str, splits: list[str], rerun_inference: bool) -> Job:
        dataset_dir = self.datasets.dataset_dir(dataset_id)
        for split in splits:
            self.datasets.check_split(dataset_id, split)
        key = f"{dataset_id}:{','.join(sorted(splits))}"
        if self.jobs.active("evaluation", key):
            raise ConflictError(f"an evaluation of {splits} is already running")

        def work(ctx: JobContext) -> dict[str, Any]:
            files = []
            for i, split in enumerate(splits):
                path = self.datasets.predictions_path(dataset_id, split)
                if rerun_inference or not path.is_file():
                    ctx.progress(i / len(splits) * 0.9, f"running inference on {split}")
                    self.inference.run_split_sync(dataset_id, split, ctx, i, len(splits))
                files.append(path)
            ctx.progress(0.92, "scoring predictions")
            evaluation_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
            out_dir = self._dir(dataset_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            combined = out_dir / f"{evaluation_id}.predictions.jsonl"
            with JsonlWriter(combined) as writer:
                for path in files:
                    writer.write_many(iter_jsonl(path))
            report = evaluate_predictions(dataset_dir, combined, splits, self.datasets.config)
            combined.unlink()
            record = {
                "evaluation_id": evaluation_id,
                "dataset_id": dataset_id,
                "splits": splits,
                "created_at": datetime.now(UTC).isoformat(),
                "confidence_threshold": self.inference.config.confidence_threshold,
                "report": report,
            }
            (out_dir / f"{evaluation_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            overall = report["overall"]
            return {
                "evaluation_id": evaluation_id,
                **{k: overall[k] for k in ("edge_precision", "edge_recall", "edge_f1", "coverage")},
            }

        return self.jobs.submit("evaluation", {"key": key, "dataset_id": dataset_id, "splits": splits}, work)

    def _load(self, path: Path) -> dict[str, Any]:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return record

    def _summary(self, record: dict[str, Any]) -> EvaluationSummary:
        overall = record["report"]["overall"]
        return EvaluationSummary(
            evaluation_id=record["evaluation_id"],
            dataset_id=record["dataset_id"],
            splits=record["splits"],
            created_at=record["created_at"],
            edge_precision=overall["edge_precision"],
            edge_recall=overall["edge_recall"],
            edge_f1=overall["edge_f1"],
            coverage=overall["coverage"],
            penalized_score=overall["penalized_score"],
        )

    def list(self, dataset_id: str) -> list[EvaluationSummary]:
        self.datasets.dataset_dir(dataset_id)
        directory = self._dir(dataset_id)
        if not directory.is_dir():
            return []
        records = [self._load(p) for p in directory.glob("*.json")]
        return sorted((self._summary(r) for r in records), key=lambda s: s.created_at, reverse=True)

    def get(self, dataset_id: str, evaluation_id: str) -> EvaluationReport:
        path = self._dir(dataset_id) / f"{evaluation_id}.json"
        if "/" in evaluation_id or "\\" in evaluation_id or not path.is_file():
            raise NotFoundError(f"evaluation '{evaluation_id}' not found")
        record = self._load(path)
        return EvaluationReport(**self._summary(record).model_dump(), report=record["report"])

    def company(self, dataset_id: str, company_id: str) -> CompanyEvaluation:
        view = self.inference.company(dataset_id, company_id)
        truth_dir = self.datasets.dataset_dir(dataset_id) / GROUND_TRUTH_DIR / view.split
        managers = {
            row["employee_id"]: row["manager_employee_id"]
            for row in iter_jsonl(truth_dir / GROUND_TRUTH_FILES["reporting_edges"])
            if row["company_id"] == company_id
        }
        departed = {
            row["employee_id"]
            for row in iter_jsonl(truth_dir / GROUND_TRUTH_FILES["departed_employees"])
            if row["company_id"] == company_id
        }
        counts = EdgeCounts()
        calibration = Calibration(10)
        for prediction in view.inference.predictions:
            eid = prediction.employee_id
            if eid in managers:
                outcome = counts.record_current(managers[eid], prediction.predicted_manager_id, True, False)
            elif eid in departed:
                outcome = counts.record_departed(prediction.predicted_manager_id)
            else:
                continue
            if outcome is not None:
                calibration.record(prediction.confidence, outcome)
        penalty = self.datasets.config.dataset.evaluation.wrong_edge_penalty
        metrics = counts.metrics(penalty)
        metrics["calibration"] = {k: v for k, v in calibration.to_dict().items() if k != "reliability"}
        return CompanyEvaluation(company_id=company_id, metrics=metrics)
