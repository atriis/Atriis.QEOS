from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from src.auth.db.session import SessionLocal, get_db
from src.auth.models.user import User
from src.auth.utils.tokens import decode_token, is_access_token
from src.auth.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")
# Same scheme, but a missing header yields None instead of a 401: for logout, which must clear its
# cookies even when the access token is gone or expired
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

# NOTE: get_db is imported from db.session above and deliberately NOT redefined here.
# It used to be shadowed by an identical local definition, which meant tests overriding
# db.session.get_db had no effect on endpoints (they resolve deps.get_db) and silently
# ran against the real Postgres instance instead of the SQLite test database.

def user_from_access_token(db: Session, token: Optional[str]) -> Optional[User]:
    """The user a valid access token names, or None (missing, expired, forged, not an access token,
    unknown user). get_current_user turns None into 401; logout uses it without raising."""
    if not token:
        return None
    try:
        payload = decode_token(token)
        if not is_access_token(payload):
            # MFA challenge / service / refresh / Grafana tokens share the key and `sub` but are not sessions
            return None
        user_id: int = int(payload.get("sub"))
    except (ValueError, TypeError):
        return None
    return db.query(User).filter(User.id == user_id).first()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    user = user_from_access_token(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_active_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    # users.py has always depended on this; it was never defined, so importing the app
    # raised AttributeError and the service could not start.
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user
