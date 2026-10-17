from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from src.organization.db.session import get_db
from src.organization.utils.tokens import decode_token, is_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = decode_token(token)
        if not is_access_token(payload):
            raise ValueError("not a user access token")
        return int(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise credentials_exception


def require_org_role(*roles: str):
    # local imports avoid a service->deps->service cycle
    from src.organization.service.member_service import get_role
    from src.organization.service.organization_service import get_organization

    def dependency(
        org_id: int,
        db: Session = Depends(get_db),
        user_id: int = Depends(get_current_user_id),
    ) -> str:
        # get_organization filters out soft-deleted orgs, so a deleted org is invisible to every guarded route
        if get_organization(db, org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        role = get_role(db, org_id, user_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this organization")
        if role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return role

    return dependency


def require_active_superuser(user_id: int = Depends(get_current_user_id)) -> int:
    """The caller is an active superuser, as auth-service knows them now: the access token carries only `sub`, and
    a superuser flag in it would outlive a revocation by up to an hour."""
    from src.organization.utils.auth_client import AuthServiceUnavailable, is_active_superuser

    try:
        allowed = is_active_superuser(user_id)
    except AuthServiceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superusers only")
    return user_id


__all__ = ["get_db", "get_current_user_id", "require_org_role", "require_active_superuser"]
