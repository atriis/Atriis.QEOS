from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.ingestion.schemas.collect import _replace_unstorable


class LogPatternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The real limits (32, 256, 500) are checked by the service with a reason and its field
    name: str = Field(max_length=64)
    pattern: str = Field(max_length=1024)
    link_template: Optional[str] = Field(None, max_length=2048)


class LogPatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern: str
    link_template: Optional[str] = None
    created_at: Optional[datetime] = None


class LogScanOut(BaseModel):
    state: Literal["idle", "running"]
    since: Optional[datetime] = None


class LogPatternListOut(BaseModel):
    patterns: List[LogPatternOut]
    scan: LogScanOut


class LogPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)
    pattern: str = Field(max_length=1024)
    sample: str = Field(max_length=65_536)

    # Like an uploaded log: a NUL or a lone surrogate is replaced, never refused. Before the length check, which
    # cannot read a lone surrogate (a 422 naming the sample, not the pattern's field)
    _clean_sample = field_validator("sample", mode="before")(
        lambda value: _replace_unstorable(value) if isinstance(value, str) else value
    )


class LogPreviewOut(BaseModel):
    masked: str
    values: List[str]
