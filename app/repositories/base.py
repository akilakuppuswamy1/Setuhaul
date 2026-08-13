"""Base repository with pagination support."""

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    model: type[T]
    order_by_columns: tuple[Any, ...]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, entity_id: UUID) -> T | None:
        return self.session.get(self.model, entity_id)

    def _build_query(self, **filters: Any) -> Select[tuple[T]]:
        stmt: Select[tuple[T]] = select(self.model)
        return self._apply_filters(stmt, **filters)

    def _apply_filters(self, stmt: Select[tuple[T]], **filters: Any) -> Select[tuple[T]]:
        return stmt

    def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> tuple[list[T], int]:
        stmt = self._build_query(**filters)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        stmt = stmt.order_by(*self.order_by_columns)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = list(self.session.scalars(stmt).all())
        return items, total
