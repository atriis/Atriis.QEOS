from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictBool


class CollectionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collect_manual: StrictBool


class CollectionSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collect_manual: bool
    discarded_count: int
    last_discarded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
