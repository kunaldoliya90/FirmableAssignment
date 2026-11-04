# Liveness and readiness probes
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from firmable import __version__
from firmable.api.deps import Services

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
def health(services: Services) -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "environment": services.settings.environment}


@router.get("/health/ready", summary="Readiness probe: configuration and datasets are available")
def ready(services: Services) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        services.datasets.config  # noqa: B018
        checks["generator_config"] = "ok"
    except Exception as exc:
        checks["generator_config"] = f"error: {exc}"
    datasets_dir = services.settings.datasets_dir
    checks["datasets_dir"] = "ok" if datasets_dir.is_dir() else f"missing: {datasets_dir}"
    datasets = [d.dataset_id for d in services.datasets.list()] if datasets_dir.is_dir() else []
    checks["datasets"] = datasets
    ok = checks["generator_config"] == "ok" and checks["datasets_dir"] == "ok"
    return {"status": "ready" if ok else "degraded", "checks": checks}
