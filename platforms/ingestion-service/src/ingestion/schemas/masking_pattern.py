from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.ingestion.schemas.collect import _replace_unstorable


class MaskingPatternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)
    pattern: str = Field(max_length=1024)  # the real limit (256) is checked with a readable reason


class MaskingPatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern: str
    created_at: Optional[datetime] = None


class MaskingPreviewIn(MaskingPatternCreate):
    sample: str = Field(max_length=10_000)

    # Like an uploaded message: a NUL or a lone surrogate is replaced, never refused. Before the length check,
    # which cannot read a lone surrogate
    _clean_sample = field_validator("sample", mode="before")(
        lambda value: _replace_unstorable(value) if isinstance(value, str) else value
    )


class MaskingPreviewOut(BaseModel):
    masked: str
    matches: int
