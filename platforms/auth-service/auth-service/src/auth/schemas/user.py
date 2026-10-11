# src/services/auth-service/src/auth/schemas/user.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, List
from datetime import datetime

# Request bodies reject unknown fields. Pydantic's default is to ignore them, which turns a
# privileged field the schema no longer accepts into a silent no-op: the caller sends
# {"is_superuser": true}, gets 200, and nothing says it was discarded. Rejecting makes the
# boundary observable, and makes a test for it able to fail.
STRICT_INPUT = ConfigDict(extra="forbid")


class UserBase(BaseModel):
    # Shared by input and output schemas, so it carries no privileged field. is_active and
    # is_superuser live on the response models below. They were here, which meant
    # POST /auth/register accepted {"is_superuser": true} in its body -- harmless only
    # because create_user happens not to copy it, one line away from being an escalation.
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None

class UserCreate(UserBase):
    # Optional because SSO creates users with no password at all (the column is nullable for
    # exactly that case, and authenticate_user refuses password login when no hash exists).
    # Registration still enforces a password -- see RegisterRequest below.
    password: Optional[str] = Field(None, min_length=8)

class RegisterRequest(UserBase):
    # Self-registration must always set a password. UserCreate allows None so the SSO path
    # can create passwordless accounts; without this split, /auth/register would accept a
    # passwordless signup that can never be logged into -- letting anyone squat an address
    # its real owner could then never register.
    model_config = STRICT_INPUT

    password: str = Field(..., min_length=8)

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None

class UserSelfUpdate(BaseModel):
    # What a user may change about their own account. Deliberately excludes is_active and
    # is_superuser: PUT /users/me accepted the full UserUpdate, and update_user setattr'd
    # whatever arrived, so any user could POST {"is_superuser": true} and promote themselves.
    #
    # `email` is absent too, and that is the bigger one. Changing it required no password and
    # no proof of the new address, so any authenticated user could take any unregistered
    # address in one request -- ceo@corp.com -- which permanently locks its real owner out
    # (registration answers "Email already registered", Google SSO answers 409) and makes
    # every downstream service that keys on email see the squatter as that person. Changing
    # an address safely needs a confirm-the-new-address flow, which does not exist; until it
    # does, the field is not accepted here.
    model_config = STRICT_INPUT

    # Same floor registration enforces. Without it this route accepted a one-character
    # password, which is a way to downgrade an account's credential rather than change it.
    password: Optional[str] = Field(None, min_length=8)
    # Required when `password` is set. A stolen access token is bearer-only and lives for
    # days; without this, holding one for a minute is enough to take the account permanently
    # by replacing the password the real owner logs in with.
    current_password: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None

class UserInDB(UserBase):
    id: int
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class User(UserBase):
    id: int
    is_active: bool = True
    is_superuser: bool = False
    mfa_enabled: bool = False
    tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class UserMe(User):
    # GET /users/me only: "/grafana/" for a superuser while MONITORING_ENABLED, else null (ADR-027).
    # The dashboard shows its Monitoring item only when this is set.
    monitoring_url: Optional[str] = None
