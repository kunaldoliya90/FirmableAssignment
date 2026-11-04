# Inference routes: per-company inference, org chart, unresolved employees and split jobs
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from firmable.api.deps import PageParam, PageSizeParam, Services
from firmable.schemas.common import Page
from firmable.schemas.inference import (
    CompanyInferenceOut,
    InferenceRunOut,
    OrgChart,
    SplitInferenceRequest,
    UnresolvedEmployee,
)
from firmable.schemas.jobs import JobOut

router = APIRouter(tags=["inference"])


@router.post(
    "/datasets/{dataset_id}/companies/{company_id}/inference",
    response_model=CompanyInferenceOut,
    summary="Infer the reporting graph of one company from observed data",
)
def infer_company(
    dataset_id: str, company_id: str, services: Services, refresh: bool = False
) -> CompanyInferenceOut:
    view = services.inference.company(dataset_id, company_id, refresh=refresh)
    stats: dict[str, Any] = view.inference.stats
    return CompanyInferenceOut(
        company_id=company_id,
        employees=stats["employees"],
        predicted_edges=stats["predicted_edges"],
        abstentions=stats["abstentions"],
        departed_detected=stats["departed_detected"],
        root_id=stats["root_id"],
        decision_reasons=stats["decision_reasons"],
        confidence_threshold=services.inference.config.confidence_threshold,
        elapsed_seconds=stats["elapsed_seconds"],
    )


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}/org-chart",
    response_model=OrgChart,
    summary="Inferred org chart, expanded lazily from a root",
)
def org_chart(
    dataset_id: str,
    company_id: str,
    services: Services,
    root_id: Annotated[
        str | None, Query(description="Expand from this employee (default: inferred roots)")
    ] = None,
    depth: Annotated[int, Query(ge=0, le=6)] = 2,
    max_children: Annotated[int, Query(ge=1, le=500)] = 50,
) -> OrgChart:
    return services.orgchart.chart(dataset_id, company_id, root_id, depth, max_children)


@router.get(
    "/datasets/{dataset_id}/companies/{company_id}/org-chart/unresolved",
    response_model=Page[UnresolvedEmployee],
    summary="Employees without a confident manager (abstentions), with the best tentative candidate",
)
def unresolved(
    dataset_id: str,
    company_id: str,
    services: Services,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    reason: Annotated[
        str | None, Query(description="below_threshold, departed, no_candidates, cycle_broken")
    ] = None,
) -> Page[UnresolvedEmployee]:
    return services.orgchart.unresolved(dataset_id, company_id, page, page_size, reason)


@router.post(
    "/datasets/{dataset_id}/inference",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run inference over whole splits in the background and store predictions",
)
def run_inference(dataset_id: str, request: SplitInferenceRequest, services: Services) -> JobOut:
    return JobOut.of(services.inference.run_splits(dataset_id, request.splits))


@router.get(
    "/datasets/{dataset_id}/inference",
    response_model=list[InferenceRunOut],
    summary="Stored split predictions",
)
def inference_runs(dataset_id: str, services: Services) -> list[InferenceRunOut]:
    return [InferenceRunOut(**run) for run in services.inference.runs(dataset_id)]
