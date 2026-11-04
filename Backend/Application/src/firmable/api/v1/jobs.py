# Background job status routes
from __future__ import annotations

from fastapi import APIRouter

from firmable.api.deps import Services
from firmable.schemas.jobs import JobOut

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut], summary="Background jobs (newest first)")
def list_jobs(services: Services) -> list[JobOut]:
    return [JobOut.of(job) for job in services.jobs.list()]


@router.get("/jobs/{job_id}", response_model=JobOut, summary="Job status and result")
def get_job(job_id: str, services: Services) -> JobOut:
    return JobOut.of(services.jobs.get(job_id))
