# src/services/auth-service/src/auth/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class GoogleLoginRequest(BaseModel):
    credential: str

class LinkGoogleRequest(BaseModel):
    credential: str
    # Required to link Google to an account that already has a password: an authenticated
    # bearer token can be short-lived and stolen, and linking a new, durable login method is
    # exactly the kind of change that must not be reachable by holding one for a minute.
    # Not required for a passwordless account, which has nothing to confirm against.
    current_password: Optional[str] = None

class GitHubLoginRequest(BaseModel):
    code: str

class MicrosoftLoginRequest(BaseModel):
    credential: str  # the ID token MSAL returns


class LinkMicrosoftRequest(BaseModel):
    credential: str
    # Same rule as LinkGoogleRequest: required when the account has a password
    current_password: Optional[str] = None

class AuthMethods(BaseModel):
    # GET /auth/methods (public, ADR-031). password is false in SSO-only mode: the superuser
    # break-glass is not advertised. providers: configured, limited to AUTH_SSO_PROVIDERS in the mode.
    password: bool
    providers: List[str]

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshTokenRequest(BaseModel):
    # /auth/refresh-token and /auth/logout previously declared `refresh_token: str` as a bare
    # parameter, which FastAPI reads as a QUERY parameter -- so a JSON body could never
    # satisfy them and both always returned 422.
    # Optional since the httpOnly qeos_refresh cookie became the browser path; API
    # clients keep sending it in the body.
    refresh_token: Optional[str] = None

class MfaCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)

class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(..., min_length=4, max_length=16)

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    password: str = Field(..., min_length=8)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

class ResendVerificationRequest(BaseModel):
    email: EmailStr