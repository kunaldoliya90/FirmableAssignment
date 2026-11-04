# FastAPI entry point: `uvicorn firmable.main:app` or the `firmable-api` script
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from firmable import __version__
from firmable.api.v1 import router as v1_router
from firmable.core.errors import install_error_handlers
from firmable.core.middleware import RequestLoggingMiddleware
from firmable.services import ServiceContainer
from Infra import get_settings
from Infra.Common.BaseSettings import CommonSettings
from Infra.Common.Logging import configure_logging


def create_app(settings: CommonSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.services.jobs.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Org-chart inference platform: synthetic dataset generation, inference of reporting lines "
            "from observed employee records, org-chart exploration and evaluation against "
            "hidden ground truth."
        ),
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url=f"{settings.api_prefix}/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.services = ServiceContainer.build(settings)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(v1_router, prefix=settings.api_prefix)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "firmable.main:app",
        host="0.0.0.0",
        port=8000,
        reload=bool(getattr(settings, "reload", False)),
        log_config=None,
    )
