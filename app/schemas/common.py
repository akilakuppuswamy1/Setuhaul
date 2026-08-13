"""Shared API schema types."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-based)")
    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
