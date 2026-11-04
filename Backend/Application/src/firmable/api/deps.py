# Dependency providers
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request

from firmable.services import ServiceContainer


def get_services(request: Request) -> ServiceContainer:
    services: ServiceContainer = request.app.state.services
    return services


Services = Annotated[ServiceContainer, Depends(get_services)]
PageParam = Annotated[int, Query(ge=1, description="1-based page number")]
PageSizeParam = Annotated[int, Query(ge=1, le=500, description="Items per page")]
