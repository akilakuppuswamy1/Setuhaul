from datetime import datetime
from uuid import UUID

from sqlalchemy import Select

from app.models.driver_exception import DriverException
from app.models.enums import ExceptionStatus, ExceptionType
from app.repositories.base import BaseRepository


class DriverExceptionRepository(BaseRepository[DriverException]):
    model = DriverException
    order_by_columns = (DriverException.occurred_at, DriverException.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[DriverException]],
        *,
        shipment_id: UUID | None = None,
        driver_id: UUID | None = None,
        exception_status: ExceptionStatus | None = None,
        **_: object,
    ) -> Select[tuple[DriverException]]:
        if shipment_id is not None:
            stmt = stmt.where(DriverException.shipment_id == shipment_id)
        if driver_id is not None:
            stmt = stmt.where(DriverException.driver_id == driver_id)
        if exception_status is not None:
            stmt = stmt.where(DriverException.status == exception_status)
        return stmt

    def list_by_shipment(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DriverException], int]:
        return self.list_paginated(page=page, page_size=page_size, shipment_id=shipment_id)

    def create(
        self,
        *,
        shipment_id: UUID,
        driver_id: UUID | None,
        exception_type: ExceptionType,
        description: str | None,
        occurred_at: datetime,
        status: ExceptionStatus = ExceptionStatus.OPEN,
    ) -> DriverException:
        entity = DriverException(
            shipment_id=shipment_id,
            driver_id=driver_id,
            exception_type=exception_type,
            description=description,
            status=status,
            occurred_at=occurred_at,
        )
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return entity
