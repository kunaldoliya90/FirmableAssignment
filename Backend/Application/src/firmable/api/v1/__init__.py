# Version 1 of the HTTP API
from fastapi import APIRouter

from firmable.api.v1 import companies, datasets, employees, evaluation, health, inference, jobs

router = APIRouter()
for module in (health, datasets, companies, employees, inference, evaluation, jobs):
    router.include_router(module.router)

__all__ = ["router"]
