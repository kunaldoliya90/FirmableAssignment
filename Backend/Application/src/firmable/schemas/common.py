# Pagination and error response shapes shared by every route
from __future__ import annotations

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


def paginate[T](items: list[T], page: int, page_size: int) -> Page[T]:
    start = (page - 1) * page_size
    return Page[T](items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)
