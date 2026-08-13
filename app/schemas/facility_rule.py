from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FacilityRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facility_id: UUID
    rule_type: str
    rule_value: dict[str, Any]
    effective_start: datetime
    effective_end: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
