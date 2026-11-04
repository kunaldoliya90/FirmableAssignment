# Evaluation routes: evaluation jobs, stored reports and per-company metrics
from __future__ import annotations

from fastapi import APIRouter, status

from firmable.api.deps import Services
from firmable.schemas.evaluation import (
    CompanyEvaluation,
    EvaluationReport,
    EvaluationRequest,
    EvaluationSummary,
)
from firmable.schemas.jobs import JobOut

router = APIRouter(tags=["evaluation"])


@router.post(
    "/datasets/{dataset_id}/evaluations",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Evaluate split predictions against hidden ground truth (infers missing splits first)",
)
def run_evaluation(dataset_id: str, request: EvaluationRequest, services: Services) -> JobOut:
    return JobOut.of(services.evaluation.run(dataset_id, request.splits, request.rerun_inference))


@router.get(
    "/datasets/{dataset_id}/evaluations", response_model=list[EvaluationSummary], summary="Past evaluations"
)
def list_evaluations(dataset_id: str, services: Services) -> list[EvaluationSummary]:
    return services.evaluation.list(dataset_id)


@router.get(
    "/datasets/{dataset_id}/evaluations/{evaluation_id}",
    response_model=EvaluationReport,
    summary="Full evaluation report (metrics, calibration, breakdowns)",
)
def get_evaluation(dataset_id: str, evaluation_id: str, services: Services) -> EvaluationReport:
    return services.evaluation.get(dataset_id, evaluation_id)


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}/evaluation",
    response_model=CompanyEvaluation,
    summary="Aggregate accuracy of one company's inferred graph (no ground-truth edges are returned)",
)
def company_evaluation(dataset_id: str, company_id: str, services: Services) -> CompanyEvaluation:
    return services.evaluation.company(dataset_id, company_id)
