from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator


class CollectionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A field left out stays as it is; at least one must be sent
    collect_manual: Optional[StrictBool] = None
    keep_screenshots: Optional[StrictBool] = None

    @model_validator(mode="after")
    def _something_to_change(self):
        if self.collect_manual is None and self.keep_screenshots is None:
            raise ValueError("send collect_manual or keep_screenshots")
        return self


class CollectionSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collect_manual: bool
    keep_screenshots: bool
    discarded_count: int
    last_discarded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
