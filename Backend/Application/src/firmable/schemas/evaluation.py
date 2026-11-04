# Evaluation request and report models
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvaluationRequest(BaseModel):
    splits: list[str] = Field(default_factory=lambda: ["test"])
    rerun_inference: bool = False


class EvaluationSummary(BaseModel):
    evaluation_id: str
    dataset_id: str
    splits: list[str]
    created_at: datetime
    edge_precision: float | None
    edge_recall: float | None
    edge_f1: float | None
    coverage: float | None
    penalized_score: float | None


class EvaluationReport(EvaluationSummary):
    report: dict[str, Any]


class CompanyEvaluation(BaseModel):
    company_id: str
    metrics: dict[str, Any]
