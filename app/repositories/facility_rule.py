from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select

from app.models.facility_rule import FacilityRule
from app.repositories.base import BaseRepository


class FacilityRuleRepository(BaseRepository[FacilityRule]):
    model = FacilityRule
    order_by_columns = (FacilityRule.effective_start, FacilityRule.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[FacilityRule]],
        *,
        facility_id: UUID | None = None,
        is_active: bool | None = None,
        **_: object,
    ) -> Select[tuple[FacilityRule]]:
        if facility_id is not None:
            stmt = stmt.where(FacilityRule.facility_id == facility_id)
        if is_active is not None:
            stmt = stmt.where(FacilityRule.is_active == is_active)
        return stmt

    def list_by_facility(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FacilityRule], int]:
        return self.list_paginated(page=page, page_size=page_size, facility_id=facility_id)

    def list_active_at(self, facility_id: UUID, at_time: datetime) -> list[FacilityRule]:
        stmt = (
            select(FacilityRule)
            .where(FacilityRule.facility_id == facility_id)
            .where(FacilityRule.is_active.is_(True))
            .where(FacilityRule.effective_start <= at_time)
            .where(
                or_(
                    FacilityRule.effective_end.is_(None),
                    FacilityRule.effective_end > at_time,
                )
            )
            .order_by(FacilityRule.effective_start, FacilityRule.id)
        )
        return list(self.session.scalars(stmt).all())
