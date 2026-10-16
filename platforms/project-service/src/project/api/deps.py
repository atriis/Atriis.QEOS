from typing import NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from src.project.db.session import get_db
from src.project.models.project import Project
from src.project.utils import org_client
from src.project.utils.tokens import decode_token, is_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

MANAGE_ROLES = ("owner", "admin")
EDIT_ROLES = ("owner", "admin", "member")
READ_ROLES = org_client.ORG_ROLES


class Caller(NamedTuple):
    user_id: int
    token: str


class OrgAccess(NamedTuple):
    org_id: int
    user_id: int
    role: str


class ProjectAccess(NamedTuple):
    project: Project
    user_id: int
    role: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_caller(token: str = Depends(oauth2_scheme)) -> Caller:
    if token is None:
        raise _unauthorized()
    try:
        claims = decode_token(token)
        if not is_access_token(claims):
            raise ValueError("not a user access token")
        return Caller(user_id=int(claims["sub"]), token=token)
    except (ValueError, KeyError, TypeError):
        raise _unauthorized()


def role_in(org_id: int, caller: Caller, not_found_detail: str) -> str:
    try:
        return org_client.get_my_role(org_id, caller.token)
    except org_client.NotAMember:
        # never 403: a non-member must not learn that the organization or project exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    except org_client.InvalidCredentials:
        raise _unauthorized()
    except org_client.OrgServiceUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Organization service unavailable")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")


def require_org_role(*roles: str):
    def dependency(org_id: int, caller: Caller = Depends(get_caller)) -> OrgAccess:
        role = role_in(org_id, caller, "Organization not found")
        if role not in roles:
            raise _forbidden()
        return OrgAccess(org_id=org_id, user_id=caller.user_id, role=role)

    return dependency


def require_project_role(*roles: str):
    def dependency(
        project_id: int,
        db: Session = Depends(get_db),
        caller: Caller = Depends(get_caller),
    ) -> ProjectAccess:
        project = (
            db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).first()
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        # The organization comes from the project row, never from the URL
        org_id = project.organization_id
        # End the read-only transaction before the HTTP call: a slow
        # organization-service must not hold this connection out of the pool.
        # The project reloads on next access, on a fresh connection.
        db.rollback()
        role = role_in(org_id, caller, "Project not found")
        if role not in roles:
            raise _forbidden()
        return ProjectAccess(project=project, user_id=caller.user_id, role=role)

    return dependency


__all__ = [
    "get_db", "get_caller", "role_in", "Caller", "require_org_role", "require_project_role",
    "OrgAccess", "ProjectAccess", "MANAGE_ROLES", "EDIT_ROLES", "READ_ROLES",
]
