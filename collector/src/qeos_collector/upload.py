"""POST one part to /api/v1/collect/runs, retrying what is worth retrying."""
from __future__ import annotations

import http.client
import json
import math
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping, Optional, Tuple

from qeos_collector import __version__
from qeos_collector.payload import Part

COLLECT_PATH = "/api/v1/collect/runs"
KEY_CHECK_PATH = "/api/v1/collect/key"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (1, 2, 4, 8)
TIME_BUDGET_SECONDS = 120
MAX_RETRY_AFTER_SECONDS = 10
MAX_DETAIL_CHARS = 500
STEP_DETAILS = ("definition", "pattern")
OLDER_PLATFORM = ("the platform is older than this collector and refused the failed step's definition and pattern: "
                  "sent again without them (upgrade QEOS to group failed steps across test cases)")


def _ignore(message: str) -> None:
    pass


class ConfigError(Exception):
    """A setting that can never work."""


class UploadError(Exception):
    """The platform did not store the part. `retryable` is True when a later
    identical attempt could succeed (outage, 429/5xx exhaustion) and False when
    it never will (401, 409, a 4xx rejection, a TLS trust problem)."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def endpoint_for(url: str) -> str:
    url = url.strip()
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    secure = parts is not None and parts.scheme == "https" and bool(host)
    local = parts is not None and parts.scheme == "http" and host in LOCAL_HOSTS
    if not (secure or local):
        raise ConfigError(f"QEOS_URL must be an https:// URL (http:// only for localhost), got {url!r}")
    return url.rstrip("/") + COLLECT_PATH


def make_context(
    ca_file: Optional[str],
    client_cert: Optional[str] = None,
    client_key: Optional[str] = None,
) -> ssl.SSLContext:
    if client_key and not client_cert:
        raise ConfigError("--client-key needs --client-cert (the certificate the key belongs to)")
    if not ca_file:
        context = ssl.create_default_context()
    else:
        # --ca-file pins trust to exactly this CA (curl --cacert semantics). Blending it
        # into the system store broke verification on Windows machines whose ROOT store
        # carries CN=localhost dev certificates (IIS Express, dotnet dev-certs): OpenSSL
        # looks anchors up by subject and can pick one with the wrong key.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # CERT_REQUIRED + hostname check
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.load_verify_locations(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ConfigError(f"cannot use --ca-file {ca_file}: {exc}") from None
    if client_cert:
        # mTLS: presented when the server asks for a client certificate
        try:
            context.load_cert_chain(certfile=client_cert, keyfile=client_key or None)
        except (OSError, ssl.SSLError) as exc:
            raise ConfigError(f"cannot use --client-cert {client_cert}: {exc}") from None
    return context


def upload_part(
    endpoint: str,
    api_key: str,
    part: Part,
    context: Optional[ssl.SSLContext] = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rand: Callable[[], float] = random.random,
    warn: Callable[[str], None] = _ignore,
) -> Tuple[int, dict]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Always sent: a retried POST whose first attempt was stored is then replayed, not stored twice
        "Idempotency-Key": part.idempotency_key,
        "User-Agent": f"qeos-collector/{__version__}",
    }
    started = clock()
    attempt = 0
    payload = part.body
    downgraded = False
    while True:
        attempt += 1
        try:
            status, body, response_headers = _send(endpoint, payload, headers, context)
        except (OSError, http.client.HTTPException) as exc:
            if _is_tls_error(exc):
                raise UploadError(
                    f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, pass --ca-file"
                ) from None
            problem, wait = f"cannot reach the platform ({_reason(exc)})", _backoff(attempt, rand)
        else:
            if status in (200, 201, 202):
                return status, _json(body)
            if status == 429:
                problem, wait = "the platform answered 429", _retry_after(response_headers)
            elif status >= 500:
                problem, wait = f"the platform answered {status}", _backoff(attempt, rand)
            else:
                # Spec 2026-10-14 §2: a server from before collector 0.8.0 forbids the two new fields. Once, and only
                # for that: nothing was stored, so the same Idempotency-Key is reused
                stripped = None if downgraded or status != 422 or not _names_failed_step(body)                     else without_step_details(payload)
                if stripped is None:
                    raise UploadError(_explain(status, body, response_headers))
                payload, downgraded = stripped, True
                warn(OLDER_PLATFORM)
                continue
        if attempt >= MAX_ATTEMPTS:
            raise UploadError(f"{problem}; gave up after {attempt} attempts", retryable=True)
        if clock() - started + wait > TIME_BUDGET_SECONDS:
            raise UploadError(f"{problem}; gave up after {TIME_BUDGET_SECONDS} s", retryable=True)
        sleep(wait)


def check_key(url: str, api_key: str, context: Optional[ssl.SSLContext] = None) -> dict:
    """GET /collect/key: proves URL, TLS and key in one request. Single attempt —
    `check` is a diagnostic, waiting through retries would hide the problem."""
    endpoint = url.strip().rstrip("/") + KEY_CHECK_PATH
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": f"qeos-collector/{__version__}",
    }
    try:
        status, body, response_headers = _send(endpoint, None, headers, context)
    except (OSError, http.client.HTTPException) as exc:
        if _is_tls_error(exc):
            raise UploadError(
                f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, pass --ca-file"
            ) from None
        raise UploadError(f"cannot reach the platform ({_reason(exc)})") from None
    if status == 200:
        return _json(body)
    if status == 401:
        raise UploadError("the API key is invalid or revoked (401)")
    if 300 <= status < 400:
        raise UploadError(
            f"the platform redirected to {response_headers.get('Location', '?')} ({status}); set QEOS_URL to that address"
        )
    raise UploadError(f"the platform answered {status}: {_detail(body)}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Following a redirect would re-send the Authorization header to wherever it points
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(
    endpoint: str, body: Optional[bytes], headers: Mapping[str, str], context: Optional[ssl.SSLContext]
) -> Tuple[int, bytes, Mapping[str, str]]:
    # build_opener keeps the default ProxyHandler, so HTTPS_PROXY / NO_PROXY are honoured
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect)
    method = "POST" if body is not None else "GET"
    request = urllib.request.Request(endpoint, data=body, headers=dict(headers), method=method)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(), exc.headers
        finally:
            exc.close()


def _is_tls_error(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    # An EOF during the handshake is a dropped connection, worth retrying; the rest will not heal
    return isinstance(reason, ssl.SSLError) and not isinstance(reason, ssl.SSLEOFError)


def _reason(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return str(reason) or type(reason).__name__


def _backoff(attempt: int, rand: Callable[[], float]) -> float:
    base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
    return base * (1 + 0.25 * rand())


def _retry_after(headers: Mapping[str, str]) -> float:
    try:
        seconds = float(headers.get("Retry-After") or "")
    except ValueError:
        return 1.0
    if not math.isfinite(seconds) or seconds < 0:
        return 1.0
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _json(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _names_failed_step(body: bytes) -> bool:
    """A validation error inside a result's failed_step (FastAPI's 422: {"detail": [{"loc": [...]}, ...]})."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, list) and any(
        isinstance(error, dict) and isinstance(error.get("loc"), list) and "failed_step" in error["loc"]
        for error in detail
    )


def without_step_details(body: bytes) -> Optional[bytes]:
    """The body without failed_step.definition and .pattern; None when it has neither (nothing to retry without)."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    removed = False
    for result in (data.get("results") if isinstance(data, dict) else None) or []:
        step = result.get("failed_step") if isinstance(result, dict) else None
        if isinstance(step, dict):
            for name in STEP_DETAILS:
                if name in step:
                    del step[name]
                    removed = True
    if not removed:
        return None
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _explain(status: int, body: bytes, headers: Mapping[str, str]) -> str:
    if status == 401:
        return "the API key is invalid or revoked (401)"
    if status == 409:
        return "this Idempotency-Key was already used for different results (409)"
    if 300 <= status < 400:
        return f"the platform redirected to {headers.get('Location', '?')} ({status}); set QEOS_URL to that address"
    return f"the platform rejected the upload ({status}): {_detail(body)}"


def _detail(body: bytes) -> str:
    try:
        detail = json.loads(body)["detail"]
    except (ValueError, KeyError, TypeError):
        text = body.decode("utf-8", errors="replace")
    else:
        text = detail if isinstance(detail, str) else json.dumps(detail)
    return text[:MAX_DETAIL_CHARS]
