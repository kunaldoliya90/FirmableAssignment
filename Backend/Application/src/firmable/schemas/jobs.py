# Background job response model
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from firmable.core.jobs import Job


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: float
    message: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, job: Job) -> JobOut:
        return cls(
            id=job.id,
            kind=job.kind,
            status=job.status,
            progress=job.progress,
            message=job.message,
            params=job.params,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
