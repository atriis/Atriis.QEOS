"""POST one part to /api/v1/collect/runs, retrying what is worth retrying; before it, the step screenshots."""
from __future__ import annotations

import http.client
import json
import math
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_for
from typing import Callable, Dict, Mapping, Optional, Set, Tuple

from qeos_collector import __version__
from qeos_collector.payload import Part
from qeos_collector.playwright_images import FileImage, image_bytes

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
LOG_FIELD = "log"
OLDER_PLATFORM_LOG = ("the platform is older than this collector and refused the results' log: sent again without "
                      "it (upgrade QEOS to see log values)")
SCREENSHOTS_FIELD = "screenshots"
OLDER_PLATFORM_SCREENSHOTS = ("the platform is older than this collector and refused the results' screenshots: sent "
                              "again without them (upgrade QEOS to see step screenshots)")
# Step screenshots (spec 2026-10-19 §5.2): the images go up before the run, each on its own, best effort
BLOBS_PATH = "/api/v1/collect/blobs/"
MAX_IMAGES_PER_RUN = 5000
IMAGE_BUDGET_SECONDS = 120
IMAGE_WORKERS = 4


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
                # A server from before this collector forbids its newer fields (spec 2026-10-14 §2: the failed step's
                # definition and pattern; log values §2.2: `log`). Once, and only for those: nothing was stored, so
                # the same Idempotency-Key is reused
                stripped = None if downgraded or status != 422 else _downgrade(payload, body, warn)
                if stripped is None:
                    raise UploadError(_explain(status, body, response_headers))
                payload, downgraded = stripped, True
                continue
        if attempt >= MAX_ATTEMPTS:
            raise UploadError(f"{problem}; gave up after {attempt} attempts", retryable=True)
        if clock() - started + wait > TIME_BUDGET_SECONDS:
            raise UploadError(f"{problem}; gave up after {TIME_BUDGET_SECONDS} s", retryable=True)
        sleep(wait)


def check_key(url: str, api_key: str, context: Optional[ssl.SSLContext] = None,
              timeout: Optional[float] = None) -> dict:
    """GET /collect/key: proves URL, TLS and key in one request. Single attempt —
    `check` is a diagnostic, waiting through retries would hide the problem."""
    endpoint = url.strip().rstrip("/") + KEY_CHECK_PATH
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": f"qeos-collector/{__version__}",
    }
    try:
        status, body, response_headers = _send(endpoint, None, headers, context, timeout=timeout)
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


class _OutOfTime(Exception):
    """The image phase's budget ran out."""


class _StopImages(Exception):
    """Every other image would get the same answer (unreachable, no access, screenshots off): stop the phase."""


def upload_images(
    base_url: str,
    key: str,
    images: "Dict[str, Tuple[str, bytes | FileImage]]",
    budget_seconds: float = IMAGE_BUDGET_SECONDS,
    workers: int = IMAGE_WORKERS,
    *,
    context: Optional[ssl.SSLContext] = None,
    warn: Callable[[str], None] = _ignore,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> Set[str]:
    """Stores each image (sha256 -> (media type, bytes)) with HEAD, then PUT when missing, on
    /collect/blobs/{sha256} before the run (spec 2026-10-19 §5.2), and returns the sha256s QEOS holds; the caller
    drops every other reference. Best effort: HTTP and network errors never raise (an unexpected error does; the
    caller catches it), and each reason images were left out is one `warn`.
    The first request goes alone, so a platform that cannot be reached costs one request, not one per image."""
    shas = list(images)
    if len(shas) > MAX_IMAGES_PER_RUN:
        warn(f"{len(shas) - MAX_IMAGES_PER_RUN} beyond {MAX_IMAGES_PER_RUN} per run")
        shas = shas[:MAX_IMAGES_PER_RUN]
    if not shas:
        return set()
    prefix = base_url.strip().rstrip("/") + BLOBS_PATH
    headers = {"Authorization": f"Bearer {key}", "User-Agent": f"qeos-collector/{__version__}"}
    # Its own budget: the run upload after it keeps its whole TIME_BUDGET_SECONDS
    deadline = clock() + budget_seconds
    lock = threading.Lock()
    stopped: list = []
    late = threading.Event()

    def store(sha: str, first: bool = False) -> bool:
        if stopped:
            return False
        if clock() >= deadline:
            late.set()
            return False
        media_type, data = images[sha]
        try:
            return _store_image(prefix + sha, headers, media_type, data, context, deadline, first=first,
                                clock=clock, sleep=sleep, rand=rand)
        except _OutOfTime:
            late.set()
        except _StopImages as exc:
            with lock:
                stopped.append(str(exc))
        return False

    # At the deadline this returns and what has not finished is left out. The pool shuts down without waiting, but its
    # threads are not daemons: up to `workers` requests still running finish in the background, each bounded by its
    # socket timeout (at most TIMEOUT_SECONDS, less when the deadline was near), and the interpreter waits for them
    # before it exits. That timeout covers each wait for data, so a server that trickles bytes can stretch it
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(store, shas[0], True): shas[0]}
        done, _ = wait_for(futures, timeout=max(0.0, deadline - clock()))
        if done and not stopped:
            futures.update({pool.submit(store, sha): sha for sha in shas[1:]})
            done, _ = wait_for(futures, timeout=max(0.0, deadline - clock()))
        stored = {futures[future] for future in done if future.result()}
        if len(done) < len(futures) and not stopped:
            late.set()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if stopped:
        warn(stopped[0])
    if late.is_set():
        warn(f"out of time after {budget_seconds:g} s")
    return stored


def _store_image(url: str, headers: Mapping[str, str], media_type: str, data: "bytes | FileImage",
                 context: Optional[ssl.SSLContext], deadline: float, *, first: bool,
                 clock: Callable[[], float], sleep: Callable[[float], None], rand: Callable[[], float]) -> bool:
    """True when QEOS holds the image: already there (HEAD 200) or stored now (PUT 200/201)."""
    status = _blob_request(url, "HEAD", None, headers, context, deadline, first, clock, sleep, rand)
    if status == 200:
        return True
    if status == 404:
        body = image_bytes(data)  # a Playwright file is read only now, and only when QEOS does not have it yet
        if body is None:
            return False  # the file changed or went away since the report was read: left out of the run
        status = _blob_request(url, "PUT", body, {**headers, "Content-Type": media_type}, context, deadline, False,
                               clock, sleep, rand)
        if status in (200, 201):
            return True
    if status == 401:
        raise _StopImages("the API key is invalid or revoked (401)")
    if status == 403:
        raise _StopImages("screenshots are off for this project (403)")
    if status == 410:
        raise _StopImages("the project is pending deletion (410)")
    if 300 <= status < 400:
        raise _StopImages(f"the platform redirected ({status})")
    return False  # this image only: refused (400, 413) or out of attempts


def _blob_request(url: str, method: str, data: Optional[bytes], headers: Mapping[str, str],
                  context: Optional[ssl.SSLContext], deadline: float, first: bool,
                  clock: Callable[[], float], sleep: Callable[[float], None], rand: Callable[[], float]) -> int:
    """The answer's status, retrying 429, 5xx and dropped connections as upload_part does but within the image
    phase's deadline; 0 when the attempts ran out."""
    attempt = 0
    while True:
        attempt += 1
        left = deadline - clock()
        if left <= 0:
            raise _OutOfTime()
        try:
            status, _, response_headers = _send(url, data, headers, context, method=method,
                                                timeout=min(TIMEOUT_SECONDS, left))
        except (OSError, http.client.HTTPException) as exc:
            if clock() >= deadline:
                raise _OutOfTime() from None
            if first or _is_tls_error(exc):
                raise _StopImages(f"cannot reach the platform ({_reason(exc)})") from None
            wait = _backoff(attempt, rand)
        else:
            if status == 429:
                wait = _retry_after(response_headers)
            elif status >= 500:
                wait = _backoff(attempt, rand)
            else:
                return status
        if attempt >= MAX_ATTEMPTS:
            return 0
        if clock() + wait > deadline:
            raise _OutOfTime()
        sleep(wait)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Following a redirect would re-send the Authorization header to wherever it points
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(
    endpoint: str, body: Optional[bytes], headers: Mapping[str, str], context: Optional[ssl.SSLContext],
    method: Optional[str] = None, timeout: Optional[float] = None,
) -> Tuple[int, bytes, Mapping[str, str]]:
    # build_opener keeps the default ProxyHandler, so HTTPS_PROXY / NO_PROXY are honoured
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect)
    method = method or ("POST" if body is not None else "GET")
    request = urllib.request.Request(endpoint, data=body, headers=dict(headers), method=method)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS if timeout is None else timeout) as response:
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


def _refused_fields(body: bytes) -> Tuple[bool, bool, bool]:
    """(step details, log, screenshots): which of this collector's newer fields a 422 forbids (FastAPI: {"detail":
    [{"loc": …}]})."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return False, False, False
    if not isinstance(detail, list):
        return False, False, False
    locs = [error["loc"] for error in detail if isinstance(error, dict) and isinstance(error.get("loc"), list)]
    step = any(loc[-2:-1] == ["failed_step"] and loc[-1] in STEP_DETAILS for loc in locs)
    log = any(len(loc) >= 3 and loc[-1] == LOG_FIELD and loc[-3] == "results" for loc in locs)
    # The field itself (an older platform) or anything inside it: a screenshot reference never costs the run
    shots = any(SCREENSHOTS_FIELD in loc and loc.index(SCREENSHOTS_FIELD) >= 2
                and loc[loc.index(SCREENSHOTS_FIELD) - 2] == "results" for loc in locs)
    return step, log, shots


def _downgrade(payload: bytes, body: bytes, warn: Callable[[str], None]) -> Optional[bytes]:
    """The payload without the newer fields the 422 names, one warning per kind; None when there is nothing to strip."""
    step, log, shots = _refused_fields(body)
    stripped, notes = None, []
    if step:
        without = without_step_details(payload)
        if without is not None:
            payload = stripped = without
            notes.append(OLDER_PLATFORM)
    if log:
        without = without_log(payload)
        if without is not None:
            payload = stripped = without
            notes.append(OLDER_PLATFORM_LOG)
    if shots:
        without = without_screenshots(payload)
        if without is not None:
            payload = stripped = without
            notes.append(OLDER_PLATFORM_SCREENSHOTS)
    for note in notes:
        warn(note)
    return stripped


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
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="replace")


def without_log(body: bytes) -> Optional[bytes]:
    """The body without the results' `log`; None when no result has one (nothing to retry without)."""
    return _without_result_field(body, LOG_FIELD)


def without_screenshots(body: bytes) -> Optional[bytes]:
    """The body without the results' `screenshots`; None when no result has them (nothing to retry without)."""
    return _without_result_field(body, SCREENSHOTS_FIELD)


def _without_result_field(body: bytes, name: str) -> Optional[bytes]:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    removed = False
    for result in (data.get("results") if isinstance(data, dict) else None) or []:
        if isinstance(result, dict) and name in result:
            del result[name]
            removed = True
    if not removed:
        return None
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="replace")


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
