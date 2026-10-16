from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from src.organization.models.member import OrganizationMember as OrganizationMemberModel


class MemberCreate(BaseModel):
    user_id: int
    role: str = Field(default="member")


class MemberOut(BaseModel):
    id: int
    organization_id: int
    user_id: int
    email: Optional[str] = None  # enriched from auth-service, best effort
    role: str
    status: str
    managed_by: Optional[str] = None  # "entra": kept in step by the app-role mapping (ADR-033)
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MyRoleOut(BaseModel):
    """Contract with project-service: exactly this one key. See the project-service design spec."""

    role: str
