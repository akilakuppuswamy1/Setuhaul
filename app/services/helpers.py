"""Service layer helpers."""

from typing import TypeVar

from pydantic import BaseModel

from app.schemas.common import PaginatedResponse

T = TypeVar("T")
R = TypeVar("R", bound=BaseModel)


def to_paginated(
    items: list[T],
    *,
    page: int,
    page_size: int,
    total: int,
    response_model: type[R],
) -> PaginatedResponse[R]:
    return PaginatedResponse(
        items=[response_model.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )
