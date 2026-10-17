"""Endpoints for other services, not for people.

Not routed by the gateway (its catch-all serves the SPA and /api/ answers the
JSON 404) and not in the public OpenAPI. Callers authenticate with HTTP Basic:
INTERNAL_API_USERNAME / INTERNAL_API_PASSWORD — the same pattern as
project-service's retention API. First consumer: organization-service's
member add, which previously needed a superuser's bearer token to ask
"does this user exist?". Second consumer: the gateway's auth_request for
/grafana/ (`grafana-check`, cookie-authenticated, no HTTP Basic)."""
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.db.session import get_db
from src.auth.models.user import User
from src.auth.utils.grafana_session import GRAFANA_COOKIE, grafana_claims, password_version

router = APIRouter()
_basic = HTTPBasic(auto_error=False)


class InternalUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_active: bool
    # organization-service lets only an active superuser approve Entra role sync for an organization (ADR-033)
    is_superuser: bool = False


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    # Both parts are always compared, so the timing does not tell which one was wrong
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_API_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


class InternalUserList(BaseModel):
    users: list[InternalUser]


MAX_BATCH_IDS = 200


@router.get("/users", response_model=InternalUserList)
def get_users(ids: str, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """Batch lookup for list views (e.g. an organization's member table).
    Unknown ids are simply absent — the caller treats them as 'not found'."""
    try:
        wanted = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="ids must be a comma-separated list of integers")
    if not wanted or len(wanted) > MAX_BATCH_IDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"ids must name between 1 and {MAX_BATCH_IDS} users")
    users = db.query(User).filter(User.id.in_(wanted)).order_by(User.id).all()
    return InternalUserList(users=[InternalUser.model_validate(u) for u in users])


@router.get("/users/{user_id}", response_model=InternalUser)
def get_user(user_id: int, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/grafana-check")
def grafana_check(request: Request, db: Session = Depends(get_db)) -> Response:
    """NGINX auth_request for every /grafana/ request (monitoring spec §4, ADR-027, Rulings 1-2).

    No HTTP Basic, unlike the other endpoints here: the subrequest carries only the browser's
    headers, and the qeos_grafana cookie is itself the credential. It answers only who that cookie's
    own user is, and the gateway never routes /internal/. The Authorization header is ignored, so an
    access token is no substitute. The user is re-read every time: a demotion, a deactivation, a
    password change or monitoring turned off cuts access on the next request.

    Every answer is `Cache-Control: no-store` with an empty body; a 401 carries no WWW-Authenticate,
    which through auth_request would make the browser pop up a Basic dialog."""
    no_store = {"Cache-Control": "no-store"}
    refused = Response(status_code=status.HTTP_401_UNAUTHORIZED, headers=no_store)
    claims = grafana_claims(request.cookies.get(GRAFANA_COOKIE))
    if claims is None:
        return refused
    user = db.get(User, claims.user_id)
    if user is None:
        return refused
    allowed = (
        settings.MONITORING_ENABLED
        and user.is_active
        and user.is_superuser
        and hmac.compare_digest(claims.password_version, password_version(user))
    )
    if not allowed:
        return refused
    # Grafana's auth proxy signs this address in; the gateway always overwrites a client's copy
    return Response(status_code=status.HTTP_200_OK, headers={**no_store, "X-QEOS-User-Email": user.email})
