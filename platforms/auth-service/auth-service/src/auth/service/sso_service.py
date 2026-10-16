"""SSO Service — real Google ID token verification.

This previously returned hardcoded identities for every provider (`user@gmail.com` and
friends) while the endpoint went on to mint real access and refresh tokens for whatever
that mock returned. Any credential string would have been accepted. It was never reachable
in practice only because this module's importers did not parse, but it was one syntax fix
away from being an unauthenticated login-as-anyone hole.

Google is now verified properly against Google's published signing keys. GitHub and Azure
are not implemented and their endpoints say so (501) rather than pretending.
"""

import logging
import time
from typing import Callable, Optional

import jwt
from jwt import PyJWK, PyJWKClient, PyJWKClientError
from pydantic import EmailStr, TypeAdapter, ValidationError

from src.auth.config import settings

logger = logging.getLogger(__name__)

APP_ROLES_MAX = 50
APP_ROLE_LENGTH = 100


def _app_roles(claims: dict) -> list[str]:
    """The ID token's Entra app roles (ADR-033): strings only, stripped, cut to 100 characters, deduplicated without
    regard to case (first one kept), at most 50."""
    raw = claims.get("roles")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        value = item.strip()[:APP_ROLE_LENGTH]
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        values.append(value)
    if len(values) > APP_ROLES_MAX:
        logger.warning("Microsoft token carries %s app roles; only the first %s are used", len(values), APP_ROLES_MAX)
        values = values[:APP_ROLES_MAX]
    return values

KEY_FETCH_TIMEOUT_SECONDS = 5
KEY_REFRESH_INTERVAL_SECONDS = 300


class ThrottledJWKClient(PyJWKClient):
    """PyJWKClient with a short timeout and a limit on forced key-set refreshes.

    PyJWKClient re-fetches the key set whenever a token names a key id it has not cached, so a
    token with a made-up `kid` made us call the provider on every request (and wait up to 30 s,
    PyJWT's default timeout). Here an unknown key id forces a re-fetch at most once per refresh
    interval; otherwise it is refused without contacting the provider.
    """

    def __init__(
        self,
        uri: str,
        *,
        timeout: int = KEY_FETCH_TIMEOUT_SECONDS,
        refresh_interval: float = KEY_REFRESH_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(uri, cache_jwk_set=True, lifespan=300, timeout=timeout)
        self._refresh_interval = refresh_interval
        self._clock = clock
        self._last_forced_refresh: Optional[float] = None

    def get_signing_key(self, kid: str) -> PyJWK:
        signing_key = self.match_kid(self.get_signing_keys(), kid)
        if signing_key is None:
            now = self._clock()
            recently = (
                self._last_forced_refresh is not None
                and now - self._last_forced_refresh < self._refresh_interval
            )
            if recently:
                raise PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
            self._last_forced_refresh = now
            signing_key = self.match_kid(self.get_signing_keys(refresh=True), kid)
            if signing_key is None:
                raise PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
        return signing_key


class SSOIdentityError(Exception):
    """The token is genuine but its identity cannot be used. The message is shown to the caller."""

# Google publishes the public keys for its ID tokens here.
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Google sets one of these two as `iss` on ID tokens.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# Module-level so the fetched key set is cached across requests rather than re-fetched per login.
_jwks_client = ThrottledJWKClient(GOOGLE_CERTS_URL)

# One key set for every Entra tenant; which tenant issued a token is checked from its claims
MICROSOFT_KEYS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
_microsoft_jwks_client = ThrottledJWKClient(MICROSOFT_KEYS_URL)
_EMAIL = TypeAdapter(EmailStr)


def _usable_email(value: object) -> bool:
    """The same rule as the user model (EmailStr): an address it rejects would otherwise only
    fail when the account is created, as a 500."""
    if not isinstance(value, str):
        return False
    try:
        _EMAIL.validate_python(value)
    except ValidationError:
        return False
    return True


class SSOConfigurationError(Exception):
    """Raised when a provider is enabled in code but not configured with its client id."""


class SSOService:
    @staticmethod
    async def validate_google_token(token: str) -> dict:
        """Verify a Google ID token and return the identity it asserts.

        Raises on anything short of a valid, correctly-audienced, unexpired token signed by
        Google. Callers must treat any exception as an authentication failure -- never fall
        back to a default identity.
        """
        if not settings.GOOGLE_CLIENT_ID:
            # Fail closed. Verifying without an audience would accept ID tokens minted for
            # *any* Google client -- i.e. any other application's users could log in here.
            raise SSOConfigurationError(
                "GOOGLE_CLIENT_ID is not configured; refusing to verify Google ID tokens"
            )

        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )

        # Checked here rather than via jwt.decode(issuer=...): PyJWT 2.8.0 compares iss with
        # a plain !=, so passing the two-element tuple Google actually uses rejected every
        # real token. Accepting a list only landed in PyJWT 2.10.
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise ValueError(f"unexpected issuer: {claims.get('iss')!r}")

        if not claims.get("email"):
            raise ValueError("Google ID token carries no email claim")

        # Require an explicit boolean true. Checking `is False` let an absent claim -- or a
        # string "false", which some Google surfaces have emitted -- through, which defeats
        # the point: an unverified address is one the caller may not control.
        if claims.get("email_verified") is not True:
            raise ValueError("Google ID token's email is not verified")

        return {
            "email": claims["email"],
            "full_name": claims.get("name"),
            "provider": "google",
            "provider_user_id": claims["sub"],
        }

    @staticmethod
    def validate_microsoft_token(token: str) -> dict:
        """Verify a Microsoft (Entra ID) v2.0 ID token from an allowed tenant.

        Every tenant's tokens are signed with the same key set, so the signature alone does not
        say which tenant issued a token: `tid` must be allowed and `iss` must name that tenant.
        """
        tenants = settings.azure_allowed_tenants
        if not settings.AZURE_CLIENT_ID or not tenants:
            # Fail closed, as for Google: without an audience, tokens for any app would pass
            raise SSOConfigurationError("AZURE_CLIENT_ID and AZURE_ALLOWED_TENANTS must be set")

        signing_key = _microsoft_jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.AZURE_CLIENT_ID,
            # Entra sets nbf to the issue time, so without leeway a server clock a second behind
            # Microsoft's refused fresh tokens
            leeway=60,
            options={"require": ["exp", "nbf", "iss", "aud", "tid", "oid"]},
        )
        if claims.get("ver") != "2.0":
            raise ValueError("not a v2.0 ID token")
        tid = str(claims["tid"])
        if tid.lower() not in tenants:
            # Logged so onboarding a customer's tenant is a matter of copying this id
            logger.warning("Microsoft sign-in refused: tenant %s is not in AZURE_ALLOWED_TENANTS", tid)
            raise ValueError("tenant is not allowed")
        if claims["iss"] != f"https://login.microsoftonline.com/{tid}/v2.0":
            raise ValueError("issuer does not match the token's tenant")

        # Entra does not verify the `email` claim: it is the user's `mail` attribute, which a tenant
        # admin can set to anyone's address. The UPN (`preferred_username`) must be on one of the
        # tenant's verified domains, so it is the address unless Microsoft vouches for `email`
        # with the optional claim xms_edov ("email domain owner verified") set to true.
        if claims.get("xms_edov") is True and claims.get("email"):
            email = claims.get("email")
        else:
            email = claims.get("preferred_username")
        if not _usable_email(email):
            raise SSOIdentityError("Microsoft account has no email address")
        return {
            "email": email,
            "full_name": claims.get("name"),
            "provider": "microsoft",
            # oid is unique only within a tenant
            "provider_user_id": f"{tid}:{claims['oid']}",
            "roles": _app_roles(claims),
        }
