from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
from src.organization.models.organization import Organization

# keep the API allowlist tied to the model's tuple / CHECK constraint
PlanTier = Literal[Organization.PLAN_TIERS]  # type: ignore[valid-type]


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    plan_tier: PlanTier = "free"


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    plan_tier: Optional[PlanTier] = None


class OrganizationOut(BaseModel):
    id: int
    name: str
    slug: str
    plan_tier: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    entra_sync_approved: bool = False

    class Config:
        from_attributes = True


class MyOrganizationOut(OrganizationOut):
    role: str


class EntraSyncUpdate(BaseModel):
    approved: bool


class EntraSyncEntry(BaseModel):
    """An organization a superuser may approve for Entra role sync (ADR-033)."""
    id: int
    name: str
    slug: str
    mappings: int
    entra_sync_approved: bool
    entra_sync_approved_at: Optional[datetime] = None
