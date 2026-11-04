# Dataset routes: discovery, facets, noise profiles, generation and validation jobs
from __future__ import annotations

from fastapi import APIRouter, status

from firmable.api.deps import Services
from firmable.schemas.datasets import DatasetDetail, DatasetSummary, GenerateDatasetRequest, NoiseProfileInfo
from firmable.schemas.jobs import JobOut

router = APIRouter(tags=["datasets"])


@router.get("/datasets", response_model=list[DatasetSummary], summary="List generated datasets")
def list_datasets(services: Services) -> list[DatasetSummary]:
    return services.datasets.list()


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail, summary="Dataset manifest summary")
def get_dataset(dataset_id: str, services: Services) -> DatasetDetail:
    return services.datasets.detail(dataset_id)


@router.get("/datasets/{dataset_id}/facets", summary="Filter values for the company explorer")
def get_facets(dataset_id: str, services: Services) -> dict[str, dict[str, int]]:
    return services.companies.facets(dataset_id)


@router.post(
    "/datasets",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a new dataset in the background (DataGenerator pipeline)",
)
def generate_dataset(request: GenerateDatasetRequest, services: Services) -> JobOut:
    return JobOut.of(services.datasets.generate(request))


@router.post(
    "/datasets/{dataset_id}/validate",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-validate an exported dataset (schema, hierarchy, leakage, checksums)",
)
def validate_dataset(dataset_id: str, services: Services) -> JobOut:
    return JobOut.of(services.datasets.validate(dataset_id))


@router.get(
    "/config/noise-profiles", response_model=list[NoiseProfileInfo], summary="Available noise profiles"
)
def noise_profiles(services: Services) -> list[NoiseProfileInfo]:
    return services.datasets.noise_profiles()
