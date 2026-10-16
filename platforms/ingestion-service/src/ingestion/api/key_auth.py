from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.ingestion.db.session import get_db
from src.ingestion.models import ApiKey
from src.ingestion.utils import metrics, project_state
from src.ingestion.utils.keys import hash_key, is_api_key

bearer = HTTPBearer(auto_error=False)


def _invalid() -> HTTPException:
    metrics.REJECTED.labels(reason="auth").inc()
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Resolved before the body is validated, so an unauthenticated caller gets 401, not 422."""
    if credentials is None or not is_api_key(credentials.credentials):
        raise _invalid()
    key = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(credentials.credentials)).first()
    if key is None or key.revoked_at is not None:
        raise _invalid()
    if project_state.is_pending(key.project_id):
        # Not a 401: the key is fine, and a restore within the deletion window brings it back (spec 2026-10-16)
        metrics.REJECTED.labels(reason="pending_deletion").inc()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Project scheduled for deletion")
    return key
