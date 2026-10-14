from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import logging
import secrets
from src.auth.api import deps
from src.auth.service.auth_service import AuthService
from src.auth.service.user_service import UserService
from src.auth.service.email_sender import EmailSender
from src.auth.schemas.auth import (
    AuthMethods, LoginRequest, MfaCodeRequest, MfaVerifyRequest, Token, PasswordResetRequest,
    PasswordResetConfirm, RefreshTokenRequest, ResendVerificationRequest, ChangePasswordRequest,
)
from src.auth.service import mfa_service
from src.auth.service.auth_mode import available_providers
from src.auth.schemas.user import RegisterRequest
from src.auth.models.pending_registration import PendingRegistration
from src.auth.models.password_reset import PasswordReset
from src.auth.models.user import User
from src.auth.utils.password import get_password_hash, verify_password
from src.auth.utils.refresh_cookie import (
    clear_refresh_cookie,
    legacy_refresh_cookie,
    read_refresh_cookie,
    set_refresh_cookie,
)
from src.auth.utils.grafana_session import (
    MONITORING_URL,
    clear_grafana_cookie,
    create_grafana_token,
    password_version,
    set_grafana_cookie,
)
from src.auth.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/methods", response_model=AuthMethods)
def auth_methods():
    """Public: how people sign in to this deployment (ADR-031). No secrets, no per-user data; the
    dashboard's login and recovery pages read it."""
    return AuthMethods(password=not settings.AUTH_SSO_ONLY, providers=available_providers())


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
def register_user(
    user_in: RegisterRequest,
    db: Session = Depends(deps.get_db)
):
    """
    Begin registration. Creates a PendingRegistration rather than a User -- the address is
    not claimed until the verification link is used. See
    docs/superpowers/specs/2026-09-24-auth-service-email-verification-design.md.

    Each attempt is its own independent row (email is not UNIQUE on this table). A prior
    version rotated an existing pending row in place on a second attempt -- that let an
    unauthenticated attacker overwrite a pending registration's PASSWORD while its
    verification link kept going to the real mailbox. See the spec's "Amendment: rotation
    allowed credential injection" for the exploit this closes.
    """
    if UserService.get_user_by_email(db, user_in.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    token = secrets.token_urlsafe(32)
    pending = PendingRegistration(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        token=token,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
    )
    db.add(pending)
    db.commit()

    # The dashboard route, not the raw API endpoint: the SPA page calls the API
    # and signs the person in, instead of showing them a JSON blob
    verification_link = f"{settings.BASE_URL}/verify-email?token={token}"
    EmailSender.send_verification_email(user_in.email, verification_link)

    return {"message": "Check your email to complete registration"}


@router.get("/verify-email", response_model=Token)
def verify_email(token: str, response: Response, db: Session = Depends(deps.get_db)):
    """
    Complete registration: turn a valid, unexpired PendingRegistration into a User and
    auto-login.
    """
    pending = db.query(PendingRegistration).filter(
        PendingRegistration.token == token
    ).first()
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        # Worthless once expired -- deleting it releases the address for a clean retry
        # rather than leaving a dead row a future registration has to keep rotating past.
        db.delete(pending)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    if UserService.get_user_by_email(db, pending.email) is not None:
        # The address was claimed by another path -- most likely Google SSO, whose
        # email_verified claim is already equivalent proof -- while this registration sat
        # unverified. The stale attempt is discarded; the real account is untouched.
        db.delete(pending)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already registered",
        )

    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        full_name=pending.full_name,
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.delete(pending)
    # Every OTHER attempt for this address (an attacker's separate registration, or an
    # earlier one the registrant abandoned) is now moot. Clean them up so none of them can
    # be independently clicked later -- excluded by id since `pending` is already staged
    # for deletion above and this must not touch that same row twice.
    db.query(PendingRegistration).filter(
        PendingRegistration.email == pending.email,
        PendingRegistration.id != pending.id,
    ).delete(synchronize_session=False)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent claim of this email between the check above and
        # this commit.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already registered",
        )
    db.refresh(user)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = AuthService.create_access_token_for_user(
        user, expires_delta=access_token_expires
    )
    refresh_token = AuthService.create_user_session(db, user).token
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/resend-verification")
def resend_verification(request: ResendVerificationRequest, db: Session = Depends(deps.get_db)):
    """
    Resend a verification link. Always answers the same way regardless of whether a
    pending registration exists, matching /forgot-password's enumeration-prevention.

    Declines to act -- same generic response, nothing sent -- whenever more than one
    unexpired attempt exists for the address. An earlier version served the oldest
    unexpired row, which closes the credential-injection exploit only when the victim
    registers before any attacker does; if an attacker registers FIRST (the pre-
    registration squat this feature exists to stop), their row is the oldest permanently,
    and resend would immediately hand the victim's own recovery action a working link for
    the attacker's password, with no timing requirement at all. Declining under ambiguity
    removes the registration-order assumption entirely. The victim's own original link is
    unaffected by any of this -- verify-email is token-scoped and never touched by another
    registration -- so this only costs the resend convenience in the narrow ambiguous case,
    never correctness.
    """
    now = datetime.now(timezone.utc)
    # Fetched and filtered in Python, not in the SQL WHERE clause: this codebase's other
    # expiry checks (verify_refresh_token, claim_refresh_token, verify_email's own check)
    # all normalize SQLite's naive datetimes in Python before comparing.
    candidates = db.query(PendingRegistration).filter(
        PendingRegistration.email == request.email
    ).order_by(
        PendingRegistration.created_at.asc(), PendingRegistration.id.asc()
    ).all()

    unexpired = []
    for candidate in candidates:
        expires_at = candidate.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > now:
            unexpired.append(candidate)

    if len(unexpired) == 1:
        pending = unexpired[0]
        pending.token = secrets.token_urlsafe(32)
        pending.expires_at = now + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)
        db.commit()
        verification_link = f"{settings.BASE_URL}/verify-email?token={pending.token}"
        EmailSender.send_verification_email(request.email, verification_link)
    # len(unexpired) == 0: nothing pending, same as today.
    # len(unexpired) > 1: ambiguous. Decline silently -- each attempt's own original link
    # still works unaffected; only this convenience path refuses.

    return {
        "message": "If a pending registration exists for this email, a new verification link has been sent"
    }


def _issue_tokens(db: Session, user: User, response: Response) -> dict:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = AuthService.create_access_token_for_user(user, expires_delta=access_token_expires)
    refresh_token = AuthService.create_user_session(db, user).token
    set_refresh_cookie(response, refresh_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/login", response_model=None)
def login_access_token(
    *,
    db: Session = Depends(deps.get_db),
    response: Response,
    form_data: LoginRequest
):
    """
    Token login. With MFA enabled the response is a five-minute challenge
    instead of a session: {"mfa_required": true, "mfa_token": ...}.
    """
    user = AuthService.authenticate_user(db, form_data.email, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_token": mfa_service.create_mfa_token(user)}
    return _issue_tokens(db, user, response)


@router.post("/mfa/verify", response_model=Token)
def mfa_verify(
    *,
    db: Session = Depends(deps.get_db),
    response: Response,
    request: MfaVerifyRequest
):
    """Complete an MFA login: challenge token plus a TOTP or recovery code."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid MFA token or code",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = mfa_service.verify_mfa_token(request.mfa_token)
    if user_id is None:
        raise invalid
    user = UserService.get_user_by_id(db, user_id)
    if not user or not user.is_active or not user.mfa_enabled:
        raise invalid
    if not mfa_service.check_code(db, user, request.code):
        raise invalid
    return _issue_tokens(db, user, response)


@router.post("/mfa/enroll")
def mfa_enroll(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """Start TOTP enrollment: a fresh secret, pending until /mfa/confirm."""
    secret, uri = mfa_service.start_enrollment(db, current_user)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/confirm")
def mfa_confirm(
    *,
    db: Session = Depends(deps.get_db),
    request: MfaCodeRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    """Prove the authenticator works; returns the recovery codes exactly once."""
    recovery = mfa_service.confirm_enrollment(db, current_user, request.code)
    if recovery is None:
        # 400: the caller is authenticated; 401 is reserved for "who are you"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    return {"recovery_codes": recovery}


@router.post("/mfa/disable")
def mfa_disable(
    *,
    db: Session = Depends(deps.get_db),
    request: MfaCodeRequest,
    current_user: User = Depends(deps.get_current_active_user)
):
    """Turn MFA off; requires a current TOTP or an unused recovery code."""
    if not mfa_service.disable(db, current_user, request.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    return {"message": "MFA disabled"}


@router.post("/refresh-token", response_model=Token)
def refresh_access_token(
    *,
    db: Session = Depends(deps.get_db),
    http_request: Request,
    response: Response,
    request: RefreshTokenRequest
):
    """
    Refresh access token using refresh token (JSON body, or the httpOnly
    cookie the browser carries).
    """
    cookie_token, _ = read_refresh_cookie(http_request)
    presented = request.refresh_token or cookie_token
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token presented",
            headers={"WWW-Authenticate": "Bearer"},
        )
    db_token, outcome = AuthService.claim_refresh_token(db, presented)

    if outcome == "replayed":
        # An already-rotated token is being presented. Rotation alone does not help here: if
        # a token was stolen, the thief rotates it and the owner's next refresh is what
        # fails, leaving the thief's chain live and the owner locked out. Treat any replay as
        # a compromised chain and end every session for that user, so both parties have to
        # authenticate again and only the one who knows the password gets back in.
        logger.warning("Refresh token replay for user %s; revoking all sessions", db_token.user_id)
        AuthService.revoke_all_user_sessions(db, db_token.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token was already used; all sessions have been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if outcome != "claimed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = UserService.get_user_by_id(db, db_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with token not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )


    # Issue new tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = AuthService.create_access_token_for_user(user, expires_delta=access_token_expires)
    new_refresh_token = AuthService.create_user_session(db, user).token
    set_refresh_cookie(response, new_refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


@router.post("/logout")
def logout_user(
    *,
    db: Session = Depends(deps.get_db),
    http_request: Request,
    request: Optional[RefreshTokenRequest] = None,
    token: Optional[str] = Depends(deps.optional_oauth2_scheme),
):
    """
    Logout user by revoking the refresh token (body or cookie). Every answer -- 200, 400 and 401
    alike -- clears the refresh cookies and the Grafana cookie, so a browser always ends signed
    out. An HTTPException would drop those Set-Cookie headers, which left both cookies alive on a
    shared machine whenever the tab had idled past the access token's 60 minutes.
    """
    status_code, body = _end_session(db, http_request, request, token)
    response = JSONResponse(status_code=status_code, content=body)
    if status_code == status.HTTP_401_UNAUTHORIZED:
        response.headers["WWW-Authenticate"] = "Bearer"
    clear_refresh_cookie(response)
    clear_grafana_cookie(response)  # the Grafana hand-off ends with the session (ADR-027)
    return response


def _end_session(
    db: Session, http_request: Request, request: Optional[RefreshTokenRequest], token: Optional[str]
) -> tuple[int, dict]:
    """Revokes what can be revoked and says how logout should answer.

    With a valid access token, only refresh tokens of that user are revoked (knowing someone else's
    token value does not let you end their session), and an unknown token is a 400. Without one
    (expired, missing), the refresh tokens presented are themselves the credential: whoever holds
    one can already spend it at /auth/refresh-token, which revokes it on rotation, so revoking it
    here grants nothing more. That case still answers 401."""
    presented = (request.refresh_token if request else None) or read_refresh_cookie(http_request)[0]
    # Both cookies can arrive (one from before the QEOS rename): end the legacy one's session too
    legacy = legacy_refresh_cookie(http_request)
    current_user = deps.user_from_access_token(db, token)
    if current_user is None:
        for value in {presented, legacy} - {None, ""}:
            AuthService.revoke_refresh_token(db, value, user_id=None)
        return status.HTTP_401_UNAUTHORIZED, {"detail": "Could not validate credentials"}
    if legacy and legacy != presented:
        AuthService.revoke_refresh_token(db, legacy, user_id=current_user.id)
    revoked = AuthService.revoke_refresh_token(db, presented, user_id=current_user.id) if presented else True
    if not current_user.is_active:
        return status.HTTP_400_BAD_REQUEST, {"detail": "Inactive user"}
    if not revoked:
        return status.HTTP_400_BAD_REQUEST, {"detail": "Invalid refresh token"}
    return status.HTTP_200_OK, {"message": "Successfully logged out"}


@router.post("/grafana-session")
def grafana_session(response: Response, current_user: User = Depends(deps.get_current_user)):
    """Hands a QEOS superuser the qeos_grafana cookie for /grafana/ (monitoring spec §4, ADR-027).
    403 unless monitoring is on and the user is an active superuser (checked here, not by
    get_current_active_user, which answers an inactive user with 400).

    Bearer access token only: no cookie authenticates this request, so a cross-site page cannot make
    a browser mint the cookie (no CSRF exposure)."""
    if not (settings.MONITORING_ENABLED and current_user.is_active and current_user.is_superuser):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Monitoring is available to superusers while it is turned on",
        )
    set_grafana_cookie(response, create_grafana_token(current_user.id, password_version(current_user)))
    return {"url": MONITORING_URL}


# Password reset: /forgot-password always answers the same thing, so it cannot be used to
# learn which addresses have accounts. The emailed token is stored only as its SHA-256, works
# once, and dies after PASSWORD_RESET_EXPIRE_MINUTES. Any successful reset or change ends every
# refresh session: whoever knew the old password must not keep a session that outlives it.

FORGOT_PASSWORD_MESSAGE = "If an account with a password exists for this email, a reset link has been sent"


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def initiate_password_reset(request: PasswordResetRequest, db: Session = Depends(deps.get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    # SSO-only accounts have no password to reset; they sign in with their provider
    if user and user.hashed_password:
        now = datetime.now(timezone.utc)
        db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        ).update({PasswordReset.used_at: now})
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(
            user_id=user.id,
            token_hash=_hash_reset_token(token),
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        ))
        db.commit()
        EmailSender.send_password_reset_email(
            user.email,
            f"{settings.BASE_URL}/reset-password?token={token}",
            settings.PASSWORD_RESET_EXPIRE_MINUTES,
        )
    return {"message": FORGOT_PASSWORD_MESSAGE}


@router.post("/reset-password")
def reset_password(request: PasswordResetConfirm, db: Session = Depends(deps.get_db)):
    now = datetime.now(timezone.utc)
    reset = db.query(PasswordReset).filter(
        PasswordReset.token_hash == _hash_reset_token(request.token),
        PasswordReset.used_at.is_(None),
        PasswordReset.expires_at > now,
    ).first()
    # Conditional update claims the link: two concurrent submissions cannot both succeed
    claimed = reset is not None and db.query(PasswordReset).filter(
        PasswordReset.id == reset.id, PasswordReset.used_at.is_(None)
    ).update({PasswordReset.used_at: now}, synchronize_session=False) == 1
    user = db.get(User, reset.user_id) if claimed else None
    if not user:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    user.hashed_password = get_password_hash(request.password)
    db.commit()
    AuthService.revoke_all_user_sessions(db, user.id)
    return {"message": "Password has been reset. Sign in with the new password."}


@router.post("/change-password", response_model=None)
def change_password(
    request: ChangePasswordRequest,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    if not current_user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account signs in with Google or Microsoft and has no password to change",
        )
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = get_password_hash(request.new_password)
    db.commit()
    AuthService.revoke_all_user_sessions(db, current_user.id)
    # This browser carries on with a fresh session; every other one is signed out
    return _issue_tokens(db, current_user, response)
