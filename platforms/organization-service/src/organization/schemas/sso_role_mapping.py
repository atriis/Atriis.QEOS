from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MappedRole = Literal["admin", "member", "viewer"]


class SsoRoleMappingCreate(BaseModel):
    app_role: str
    role: MappedRole

    @field_validator("app_role")
    @classmethod
    def _app_role(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("app_role must be 1-100 characters")
        return value


class SsoRoleMappingOut(BaseModel):
    id: int
    app_role: str
    role: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SsoRolesPush(BaseModel):
    user_id: int = Field(gt=0)
    roles: list[str] = Field(default_factory=list, max_length=50)


class SsoRoleChange(BaseModel):
    organization_id: int
    action: Literal["created", "updated", "removed"]
    from_role: Optional[str] = Field(default=None, serialization_alias="from")
    to_role: Optional[str] = Field(default=None, serialization_alias="to")


class SsoRolesResult(BaseModel):
    changes: list[SsoRoleChange]
