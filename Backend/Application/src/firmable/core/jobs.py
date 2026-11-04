# In-process background jobs (dataset generation, split inference, evaluation)
from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from firmable.core.errors import NotFoundError

log = logging.getLogger("firmable.jobs")

JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    status: JobStatus = "queued"
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobContext:
    def __init__(self, job: Job, lock: threading.Lock) -> None:
        self._job = job
        self._lock = lock

    def progress(self, fraction: float, message: str = "") -> None:
        with self._lock:
            self._job.progress = round(min(max(fraction, 0.0), 1.0), 4)
            if message:
                self._job.message = message


class JobManager:
    def __init__(self, workers: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="firmable-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, params: dict[str, Any], fn: Callable[[JobContext], dict[str, Any]]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[JobContext], dict[str, Any]]) -> None:
        with self._lock:
            job.status = "running"
            job.started_at = datetime.now(UTC)
        try:
            result = fn(JobContext(job, self._lock))
        except Exception as exc:
            log.error("job %s (%s) failed: %s", job.id, job.kind, exc)
            log.debug("%s", traceback.format_exc())
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(UTC)
            return
        with self._lock:
            job.status = "succeeded"
            job.progress = 1.0
            job.result = result
            job.finished_at = datetime.now(UTC)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError(f"job '{job_id}' not found")
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def active(self, kind: str, key: str) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.kind == kind and job.params.get("key") == key and job.status in ("queued", "running"):
                    return job
        return None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
