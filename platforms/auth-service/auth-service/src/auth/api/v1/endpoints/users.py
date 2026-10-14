from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from src.auth.api import deps
from src.auth.service.user_service import UserService
# UserInDB carries hashed_password; aliasing it as the response model leaked every user's
# bcrypt hash through /users/me, /users/ and /users/{id}. User is the public shape.
from src.auth.schemas.user import UserSelfUpdate, UserUpdate, User, UserMe
from src.auth.schemas.auth import LinkGoogleRequest, LinkMicrosoftRequest
from src.auth.models.user import User as UserModel
from src.auth.models.oauth import OAuthAccount
from src.auth.service.auth_service import AuthService
from src.auth.config import settings
from src.auth.service.auth_mode import sso_only_error
from src.auth.utils.grafana_session import MONITORING_URL
from src.auth.utils.password import verify_password
from sqlalchemy.exc import IntegrityError
# Reused rather than duplicated so this endpoint and /sso/google fail identically on a bad
# or misconfigured credential.
from src.auth.api.v1.endpoints.sso import verify_google_credential, verify_microsoft_credential

router = APIRouter()


@router.get("/", response_model=List[User])
def read_users(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(deps.get_current_active_superuser),
):
    """
    Retrieve users. Only superusers can access this endpoint.
    """
    users = UserService.get_users(db, skip=skip, limit=limit)
    return users


@router.get("/me", response_model=UserMe)
def read_user_me(
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """
    Get current user. `monitoring_url` is set only for a superuser while monitoring is on (ADR-027);
    get_current_active_user has already refused an inactive user.
    """
    me = User.model_validate(current_user, from_attributes=True)
    offered = settings.MONITORING_ENABLED and current_user.is_superuser
    return UserMe(**me.model_dump(), monitoring_url=MONITORING_URL if offered else None)


@router.put("/me", response_model=User)
def update_user_me(
    *,
    db: Session = Depends(deps.get_db),
    user_in: UserSelfUpdate,
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """
    Update own user.
    """
    changing_password = user_in.password is not None
    if changing_password and settings.AUTH_SSO_ONLY and not current_user.is_superuser:
        # The same rule as /auth/change-password in SSO-only mode (ADR-031)
        raise sso_only_error()
    if changing_password:
        if current_user.hashed_password is None:
            # An SSO account has no password to confirm, so setting a first one used to be
            # allowed unconditionally -- which converted a stolen access token, valid for
            # days and revocable by nothing, into a permanent credential on the account.
            # Adding a password to an SSO account needs its own verified flow.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Setting a password on an SSO account is not supported yet",
            )
        if not user_in.current_password or not verify_password(
            user_in.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_password is incorrect",
            )

    # current_password is a credential check, not a column. Rebuilding as UserUpdate from
    # only the fields the caller actually set keeps update_user's exclude_unset semantics --
    # an omitted field stays omitted rather than being written as None.
    user = UserService.update_user(
        db,
        current_user.id,
        UserUpdate(**user_in.model_dump(exclude_unset=True, exclude={"current_password"})),
    )

    if changing_password:
        # Changing a password is how someone reacts to a suspected compromise. Leaving the
        # attacker's refresh tokens live would make it ceremonial: they would keep minting
        # access tokens for up to 30 days.
        AuthService.revoke_all_user_sessions(db, current_user.id)

    return user


def _link_identity(db: Session, current_user: UserModel, credential: str, current_password, verify, label: str):
    """Link a verified SSO identity to the current, authenticated account.

    The remedy the sign-in endpoints' 409 ("account already exists") points at.
    """
    if current_user.hashed_password is not None:
        # A short-lived bearer token can be stolen; requiring the password before attaching a
        # new, durable login method is the same guard PUT /users/me's password change uses,
        # for the same reason. Nothing to confirm for a passwordless (pure-SSO) account.
        if not current_password or not verify_password(current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_password is incorrect",
            )

    identity = verify(credential)
    provider = identity["provider"]
    provider_user_id = identity["provider_user_id"]

    # At most one link per provider per user, enforced here rather than only relied on: the
    # sign-in path's existing_link lookup picks arbitrarily via .first() if a user held two.
    if db.query(OAuthAccount).filter(
        OAuthAccount.user_id == current_user.id,
        OAuthAccount.provider == provider,
    ).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {label} account is already linked to this account",
        )

    db.add(OAuthAccount(
        user_id=current_user.id, provider=provider, provider_user_id=provider_user_id,
    ))
    try:
        db.commit()
    except IntegrityError:
        # This exact identity is already linked to a different account -- the constraint is
        # the backstop; the pre-check above is what usually catches it first.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This {label} account is already linked to a different user",
        )

    db.refresh(current_user)
    return current_user


@router.post("/me/link/google", response_model=User, dependencies=[Depends(deps.sso_provider_allowed("google"))])
def link_google_account(
    *,
    db: Session = Depends(deps.get_db),
    request: LinkGoogleRequest,
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Link a Google identity to the current, authenticated account."""
    return _link_identity(db, current_user, request.credential, request.current_password,
                          verify_google_credential, "Google")


@router.post("/me/link/microsoft", response_model=User, dependencies=[Depends(deps.sso_provider_allowed("microsoft"))])
def link_microsoft_account(
    *,
    db: Session = Depends(deps.get_db),
    request: LinkMicrosoftRequest,
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Link a Microsoft (Entra ID) identity to the current, authenticated account."""
    return _link_identity(db, current_user, request.credential, request.current_password,
                          verify_microsoft_credential, "Microsoft")


@router.get("/{user_id}", response_model=User)
def read_user_by_id(
    user_id: int,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """
    Get a specific user by id.
    """
    user = UserService.get_user_by_id(db, user_id)
    if user is not None and user.id == current_user.id:
        return user
    if not current_user.is_superuser:
        # 403, not 400: the request is well-formed and the caller is authenticated, they are
        # just not allowed. get_current_active_superuser already answers 403 elsewhere.
        # Answered before the existence check so a non-superuser cannot probe which ids exist.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    if user is None:
        # Returning None into response_model=User raised ResponseValidationError -- a 500 for
        # an ordinary "no such id".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user
