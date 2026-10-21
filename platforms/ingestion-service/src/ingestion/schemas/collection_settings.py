from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


class CollectionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A field left out stays as it is; at least one must be sent
    collect_manual: Optional[StrictBool] = None
    keep_screenshots: Optional[StrictBool] = None
    keep_traces: Optional[StrictBool] = None
    trace_days: Optional[StrictInt] = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def _something_to_change(self):
        if all(value is None for value in (self.collect_manual, self.keep_screenshots, self.keep_traces, self.trace_days)):
            raise ValueError("send collect_manual, keep_screenshots, keep_traces or trace_days")
        return self


class CollectionSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collect_manual: bool
    keep_screenshots: bool
    keep_traces: bool
    trace_days: int
    discarded_count: int
    last_discarded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
