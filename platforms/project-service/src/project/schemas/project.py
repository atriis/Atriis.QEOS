from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, StringConstraints, model_validator

from src.project.schemas.settings import ProjectSettings

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Slug = Annotated[str, StringConstraints(max_length=100, pattern=SLUG_PATTERN)]


class ProjectCreate(BaseModel):
    name: Name
    slug: Optional[Slug] = None
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[Name] = None
    slug: Optional[Slug] = None
    description: Optional[str] = None

    @model_validator(mode="after")
    def _required_fields_cannot_be_nulled(self):
        for field in ("name", "slug"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LegalHoldIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class LegalHoldOut(BaseModel):
    since: datetime
    by: Optional[int] = None
    reason: Optional[str] = None


class DeletionOut(BaseModel):
    """A pending deletion (spec 2026-10-16): restorable by owners and admins until purge_at."""

    deleted_at: datetime
    deleted_by: Optional[int] = None
    purge_at: datetime


class ProjectOut(BaseModel):
    id: int
    organization_id: int
    name: str
    slug: str
    description: Optional[str] = None
    settings: ProjectSettings
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    my_role: str
    legal_hold: Optional[LegalHoldOut] = None
    deletion: Optional[DeletionOut] = None
