import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from src.casebook.api.deps import get_db
from src.casebook.core.config import settings
from src.casebook.service import purge_service

router = APIRouter()  # mounted at /internal/v1, outside the gateway's routes
_basic = HTTPBasic(auto_error=False)


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    # Both parts are always compared, so the timing does not tell which one was wrong
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_API_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal credentials",
                            headers={"WWW-Authenticate": "Basic"})


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge(project_id: int, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """Every case, label, suite, feature file, run request and CI target of the project. Idempotent."""
    purge_service.purge_project(db, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
