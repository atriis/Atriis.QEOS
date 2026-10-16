from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jwt import PyJWKClientConnectionError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.auth.api import deps
import logging
from src.auth.service.sso_service import SSOService, SSOConfigurationError, SSOIdentityError
from src.auth.service.auth_service import AuthService
from src.auth.service.user_service import UserService
from src.auth.service.sso_readiness import valid_allowance
from src.auth.service import org_roles_sync
from src.auth.schemas.auth import GoogleLoginRequest, MicrosoftLoginRequest, Token
from src.auth.schemas.user import UserCreate  # used when SSO creates a first-time user
from src.auth.models.oauth import OAuthAccount
from src.auth.models.user import User
from src.auth.config import settings
from src.auth.utils.refresh_cookie import set_refresh_cookie
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_credential(credential: str, validate: Callable[[str], dict], label: str) -> dict:
    """Verify an ID token with `validate`, raising the HTTPExceptions every SSO endpoint raises.

    Shared by the sign-in and link endpoints of every provider, so they fail the same way.
    """
    try:
        identity = validate(credential)
    except SSOConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} SSO is not configured",
        )
    except PyJWKClientConnectionError:
        # The provider's key set could not be fetched: our problem, not the caller's token.
        logger.warning("%s signing keys could not be fetched", label, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} sign-in is temporarily unavailable",
        )
    except SSOIdentityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        # Deliberately opaque: the underlying text carries JWKS URLs and internal state.
        logger.warning("%s ID token verification failed", label, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} token",
        )

    if not identity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label} token")
    return identity


def verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token, raising the same HTTPExceptions /sso/google raises."""
    import asyncio

    return verify_credential(credential, lambda c: asyncio.run(SSOService.validate_google_token(c)), "Google")


def verify_microsoft_credential(credential: str) -> dict:
    """Verify a Microsoft ID token, raising the same HTTPExceptions /sso/microsoft raises."""
    return verify_credential(credential, SSOService.validate_microsoft_token, "Microsoft")


GOOGLE_EXISTING_ACCOUNT = (
    "An account with this email already exists. Linking Google to an existing "
    "account is not supported yet."
)
MICROSOFT_EXISTING_ACCOUNT = (
    "An account with this email already exists. Sign in to it and link Microsoft "
    "with POST /api/v1/users/me/link/microsoft."
)
# In SSO-only mode an ordinary user cannot sign in with a password to link, so only a superuser's
# allowance (ADR-031) can attach this identity to the account.
MICROSOFT_EXISTING_ACCOUNT_SSO_ONLY = (
    "An account with this email already exists but is not linked to Microsoft. "
    "Ask an administrator to allow linking at your next Microsoft sign-in."
)


def _link_or_create_user(db: Session, identity: dict, email: str, provider: str, provider_user_id: str,
                         label: str, existing_account_detail: str):
    """Resolve an SSO identity that is not yet linked to any account.

    Reached only when no OAuthAccount matches this provider and `sub`.
    """
    # Case-insensitive: providers send addresses in whatever case the directory holds (Entra UPNs are
    # often Ann.Silva@...), and an exact match missed the account and created a second, empty one.
    # Two accounts that differ only in case are ambiguous: neither is linked, and none is created.
    matches = db.query(User).filter(func.lower(User.email) == email.lower()).limit(2).all()
    if len(matches) > 1:
        logger.warning("%s sign-in for %s matches more than one account by case; not linked", label, email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=existing_account_detail)
    user = matches[0] if matches else None

    if user is None:
        user_in = UserCreate(
            email=email,
            full_name=identity.get("full_name"),
            password=None,  # SSO user -- no password
        )
        # One transaction. These used to be two commits, so a failure on the link left a
        # committed passwordless user with no link -- and since SSO no longer auto-links to
        # an existing account, that orphan answers 409 for its own address forever. A
        # transient database error would have locked an address out permanently.
        user = UserService.create_user(db, user_in, commit=False)
        db.add(OAuthAccount(
            user_id=user.id, provider=provider, provider_user_id=provider_user_id,
        ))
        try:
            db.commit()
        except IntegrityError:
            # Another request created this identity between our lookup and our commit.
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This {label} account is already linked",
            )
        db.refresh(user)
        return user

    # An account holds this address. A verified Google email proves control of the mailbox,
    # not ownership of whatever local account happens to share it. Linking on email alone is
    # a pre-registration takeover: an attacker registers victim@corp.com with a password
    # before the victim ever signs up, the victim then arrives via Google, gets attached to
    # that row, and the attacker keeps password access to everything they do there.
    existing_link = db.query(OAuthAccount).filter(
        OAuthAccount.user_id == user.id,
        OAuthAccount.provider == provider,
    ).order_by(OAuthAccount.id).first()

    if existing_link:
        # Same address, a different Google identity -- a recycled or aliased mailbox.
        # Whoever is already linked keeps the account.
        logger.warning(
            "%s identity mismatch for user %s: linked %s, presented %s",
            label, user.id, existing_link.provider_user_id, provider_user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This account is linked to a different {label} identity",
        )

    # An unlinked account already holds this address, and nothing here proves the caller owns
    # it. This used to auto-link when the row had no password, on the reasoning that a
    # passwordless row has no credential to hijack. That reasoning was wrong: a passwordless,
    # unlinked row is exactly what pre-provisioning produces -- an administrator seeds
    # ceo@corp.com ahead of time, possibly with is_superuser set -- and auto-linking handed
    # that account to whoever presented a Google token for the address first. Every producer
    # of such a row is either that seeding or a half-failed create, so there is no legitimate
    # case left to serve. Adopting SSO on an existing account needs an authenticated link
    # (POST /users/me/link/{provider}) or, for Microsoft, a superuser's allowance:
    #
    # A superuser allowed this account to link at its next Microsoft sign-in (ADR-031). Not a match on
    # the email alone: the allowance names this account, the token is from an allowed tenant (checked
    # by verify_microsoft_credential) and the account holds no Microsoft link yet (checked above).
    # Used once: the allowance is cleared by one conditional UPDATE, and only the request that changed
    # the row links. Two concurrent first sign-ins can both read a valid allowance; the row lock
    # serializes their UPDATEs and the second finds nothing to consume, so it gets the 409.
    if provider == "microsoft" and user.is_active and valid_allowance(user) is not None:
        claimed = db.query(User).filter(
            User.id == user.id,
            User.microsoft_link_allowed_until > datetime.now(timezone.utc),
        ).update({User.microsoft_link_allowed_until: None}, synchronize_session=False)
        if claimed != 1:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=existing_account_detail)
        db.add(OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_user_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This {label} account is already linked",
            )
        db.refresh(user)
        logger.warning("Microsoft identity linked to user %s (%s) through the one-time allowance", user.id, user.email)
        return user

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=existing_account_detail,
    )


def sso_sign_in(db: Session, identity: dict, label: str, *, existing_account_detail: str) -> dict:
    """Sign in with a verified SSO identity: find its account, or create one, and issue tokens."""
    email = identity["email"]
    provider = identity["provider"]
    provider_user_id = identity["provider_user_id"]

    # Resolve by the provider identity first. (provider, provider_user_id) is UNIQUE, so it is
    # the actual identity key here; the email is a mutable attribute of it. Looking up by email
    # first meant a user whose provider address had changed fell through to the create branch,
    # which committed a new user row and only then hit uix_provider_user -- a 500 with an
    # orphaned account left behind.
    linked = db.query(OAuthAccount).filter(
        OAuthAccount.provider == provider,
        OAuthAccount.provider_user_id == provider_user_id,
    ).first()

    if linked:
        # Known identity. The address on the token may have changed since; that does not
        # matter, and is deliberately not written back onto the account.
        user = UserService.get_user_by_id(db, linked.user_id)
        if not user:
            logger.error("OAuth link %s points at missing user %s", linked.id, linked.user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Account is in an inconsistent state",
            )
    else:
        user = _link_or_create_user(
            db, identity, email, provider, provider_user_id, label, existing_account_detail
        )

    # Password login refuses a deactivated account; SSO did not, so disabling someone left
    # them a working way in for as long as their provider account existed.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = AuthService.create_access_token_for_user(user, expires_delta=access_token_expires)
    refresh_token = AuthService.create_user_session(db, user).token

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/google", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("google"))])
def google_login(
    *,
    db: Session = Depends(deps.get_db),
    response: Response,
    request: GoogleLoginRequest
):
    """
    Authenticate with Google ID token.
    """
    identity = verify_google_credential(request.credential)
    tokens = sso_sign_in(db, identity, "Google", existing_account_detail=GOOGLE_EXISTING_ACCOUNT)
    set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/microsoft", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("microsoft"))])
def microsoft_login(
    *,
    db: Session = Depends(deps.get_db),
    response: Response,
    request: MicrosoftLoginRequest
):
    """
    Authenticate with a Microsoft (Entra ID) ID token from an allowed tenant.
    """
    identity = verify_microsoft_credential(request.credential)
    existing_account_detail = (
        MICROSOFT_EXISTING_ACCOUNT_SSO_ONLY if settings.AUTH_SSO_ONLY else MICROSOFT_EXISTING_ACCOUNT
    )
    tokens = sso_sign_in(db, identity, "Microsoft", existing_account_detail=existing_account_detail)
    link = db.query(OAuthAccount).filter(
        OAuthAccount.provider == "microsoft", OAuthAccount.provider_user_id == identity["provider_user_id"],
    ).first()
    org_roles_sync.record_and_push(db, link, identity.get("roles", []))
    set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


# GitHub SSO is not implemented. It previously called an SSOService method that did not exist and
# contained a syntax error, so this module never imported. Rather than resurrect a mock handler
# that returned a hardcoded identity, it fails honestly until a real OAuth exchange is built.
# (Azure was replaced by /sso/microsoft.)


# GitHub is never a valid SSO-only provider, so the mode answers its 403 before the 501
@router.post("/github", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("github"))])
def github_login():
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GitHub SSO is not implemented",
    )
