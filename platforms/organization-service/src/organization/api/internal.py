"""Endpoints for other services, not for people (ADR-033).

Not routed by the gateway and not in the public OpenAPI. auth-service authenticates with HTTP Basic:
INTERNAL_CALLER_USERNAME / INTERNAL_API_PASSWORD. Same pattern as project-service's internal API.
"""
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from src.organization.core.config import settings
from src.organization.db.session import get_db
from src.organization.schemas.sso_role_mapping import SsoRolesPush, SsoRolesResult
from src.organization.service import sso_role_service

router = APIRouter()
_basic = HTTPBasic(auto_error=False)


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_CALLER_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal credentials",
                            headers={"WWW-Authenticate": "Basic"})


@router.post("/sso-roles", response_model=SsoRolesResult, response_model_by_alias=True)
def push_sso_roles(payload: SsoRolesPush, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """A Microsoft sign-in's app roles: apply the organization mappings to this user."""
    return SsoRolesResult(changes=sso_role_service.reconcile(db, payload.user_id, payload.roles))
