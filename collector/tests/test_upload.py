import json
import socket
import threading

import pytest

from qeos_collector import __version__, upload
from qeos_collector.payload import Part
from qeos_collector.upload import ConfigError, UploadError, endpoint_for, make_context, upload_part

KEY = "qeos_test_key_123"
PART = Part(body=b'{"run":{},"results":[]}', idempotency_key="gh-1-1-test", count=0)
RECEIPT = {"id": 42, "project_id": 1, "total": 2, "passed": 1, "failed": 1, "skipped": 0, "errored": 0,
           "created_at": "2026-09-29T12:00:00Z"}


class FakeTime:
    """sleep() only records; clock() advances by `step` on every call, plus whatever was slept."""

    def __init__(self, step=0.0):
        self.now = 0.0
        self.step = step
        self.sleeps = []

    def clock(self):
        value = self.now
        self.now += self.step
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def send(endpoint, fake=None, context=None):
    fake = fake or FakeTime()
    return upload_part(endpoint, KEY, PART, context, sleep=fake.sleep, clock=fake.clock, rand=lambda: 0.0)


def collect(platform):
    return platform.url + "/api/v1/collect/runs"


def closed_port_endpoint():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/api/v1/collect/runs"


def test_a_stored_run_is_returned_with_its_status(platform):
    platform.reply(201, RECEIPT)

    assert send(collect(platform)) == (201, RECEIPT)
    request = platform.requests[0]
    assert request["path"] == "/api/v1/collect/runs"
    assert request["body"] == PART.body
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert request["headers"]["Idempotency-Key"] == "gh-1-1-test"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["headers"]["User-Agent"] == f"qeos-collector/{__version__}"


def test_a_replay_counts_as_success(platform):
    platform.reply(200, RECEIPT)
    assert send(collect(platform)) == (200, RECEIPT)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_are_retried_with_backoff(platform, status):
    platform.reply(status)
    platform.reply(status)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    assert send(collect(platform), fake) == (201, RECEIPT)
    assert fake.sleeps == [1, 2]
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-test"}


def test_backoff_has_up_to_25_percent_jitter(platform):
    platform.reply(503)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    upload_part(collect(platform), KEY, PART, sleep=fake.sleep, clock=fake.clock, rand=lambda: 1.0)
    assert fake.sleeps == [1.25]


def test_an_unreachable_platform_is_retried_until_the_attempt_budget():
    fake = FakeTime()

    with pytest.raises(UploadError, match=r"cannot reach the platform .*gave up after 5 attempts"):
        send(closed_port_endpoint(), fake)
    assert fake.sleeps == [1, 2, 4, 8]


def test_429_waits_for_retry_after_capped_at_10_seconds(platform):
    platform.reply(429, headers={"Retry-After": "3"})
    platform.reply(429, headers={"Retry-After": "60"})
    platform.reply(429)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    assert send(collect(platform), fake) == (201, RECEIPT)
    assert fake.sleeps == [3, 10, 1]


def test_no_new_attempt_starts_after_120_seconds(platform):
    for _ in range(5):
        platform.reply(503)
    fake = FakeTime(step=40)  # every clock() call is 40 s later

    with pytest.raises(UploadError, match="gave up after 120 s"):
        send(collect(platform), fake)
    assert len(platform.requests) == 3


def test_a_timed_out_post_is_retried_with_the_same_key(platform, monkeypatch):
    monkeypatch.setattr(upload, "TIMEOUT_SECONDS", 0.3)
    platform.reply(201, RECEIPT, delay=1.0)  # stored, but the answer comes too late
    platform.reply(200, RECEIPT)             # the retry is answered as a replay
    fake = FakeTime()

    assert send(collect(platform), fake) == (200, RECEIPT)
    assert fake.sleeps == [1]
    assert [r["headers"]["Idempotency-Key"] for r in platform.requests] == ["gh-1-1-test", "gh-1-1-test"]


@pytest.mark.parametrize("status, body, message", [
    (401, {"detail": "Invalid API key"}, "the API key is invalid or revoked (401)"),
    (409, {"detail": "Idempotency-Key reused"}, "this Idempotency-Key was already used for different results (409)"),
    (413, {"detail": "Request Entity Too Large"}, "the platform rejected the upload (413): Request Entity Too Large"),
    (422, {"detail": [{"loc": ["body", "run"], "msg": "Field required"}]},
     'the platform rejected the upload (422): [{"loc": ["body", "run"]'),
    (400, b"not json", "the platform rejected the upload (400): not json"),
])
def test_client_errors_are_not_retried(platform, status, body, message):
    platform.reply(status, body)
    fake = FakeTime()

    with pytest.raises(UploadError) as info:
        send(collect(platform), fake)
    assert message in str(info.value)
    assert fake.sleeps == [] and len(platform.requests) == 1


def test_the_servers_detail_is_cut_to_500_characters(platform):
    platform.reply(422, {"detail": "x" * 2000})

    with pytest.raises(UploadError) as info:
        send(collect(platform))
    assert str(info.value).endswith("x" * 500)
    assert "x" * 501 not in str(info.value)


@pytest.mark.parametrize("status", [301, 307, 308])
def test_redirects_are_not_followed(platform, status):
    # Following would re-send the Authorization header to wherever Location points
    platform.reply(status, headers={"Location": platform.url + "/elsewhere"})

    with pytest.raises(UploadError, match=f"redirected to {platform.url}/elsewhere \\({status}\\)"):
        send(collect(platform))
    assert [r["path"] for r in platform.requests] == ["/api/v1/collect/runs"]


@pytest.fixture
def not_tls():
    """A port that answers a TLS ClientHello with plain HTTP, which fails the handshake at once.

    The ClientHello is read before answering: closing a socket with unread data sends a reset,
    which the client would see as a (retryable) dropped connection instead of a TLS error.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.0 400 Bad Request\r\n\r\n")

    threading.Thread(target=serve, daemon=True).start()
    yield f"https://127.0.0.1:{listener.getsockname()[1]}/api/v1/collect/runs"
    listener.close()


def test_tls_errors_are_not_retried(not_tls):
    fake = FakeTime()

    with pytest.raises(UploadError, match="TLS error .*--ca-file"):
        send(not_tls, fake, context=make_context(None))
    assert fake.sleeps == []


@pytest.mark.parametrize("url, endpoint", [
    ("https://qeos.acme.test", "https://qeos.acme.test/api/v1/collect/runs"),
    ("https://qeos.acme.test/", "https://qeos.acme.test/api/v1/collect/runs"),
    (" https://qeos.acme.test:8443 ", "https://qeos.acme.test:8443/api/v1/collect/runs"),
    ("http://localhost:8080", "http://localhost:8080/api/v1/collect/runs"),
    ("http://127.0.0.1:9", "http://127.0.0.1:9/api/v1/collect/runs"),
    ("http://[::1]:9", "http://[::1]:9/api/v1/collect/runs"),
])
def test_endpoint_for(url, endpoint):
    assert endpoint_for(url) == endpoint


@pytest.mark.parametrize("url", ["http://qeos.acme.test", "ftp://qeos.acme.test", "qeos.acme.test", "", "https://", "http://[::1"])
def test_endpoint_for_refuses_what_cannot_work(url):
    with pytest.raises(ConfigError, match="https://"):
        endpoint_for(url)


def test_make_context_refuses_an_unusable_ca_file(tmp_path):
    not_a_cert = tmp_path / "not-a-cert.pem"
    not_a_cert.write_text("hello")

    for path in (str(not_a_cert), str(tmp_path / "missing.pem")):
        with pytest.raises(ConfigError, match="cannot use --ca-file"):
            make_context(path)


def test_make_context_with_ca_file_trusts_exactly_that_file(tmp_path):
    """--ca-file pins trust to the given CA (curl --cacert semantics). Blending
    with the system store broke on machines whose Windows ROOT store carries
    CN=localhost entries (IIS/dotnet dev certs): OpenSSL resolves the anchor by
    subject and picks one with the wrong key."""
    import ssl
    import subprocess

    crt, key = tmp_path / "tls.crt", tmp_path / "tls.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(crt)],
        check=True, capture_output=True, env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"},
    )
    context = make_context(str(crt))
    stats = context.cert_store_stats()
    assert stats["x509"] == 1, f"store must hold only the pinned CA, got {stats}"
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_make_context_without_ca_file_uses_system_defaults():
    context = make_context(None)
    assert context.cert_store_stats()["x509"] > 1  # system CAs loaded


def _self_signed(tmp_path):
    """One self-signed cert+key pair, usable as a client identity in tests."""
    import datetime
    import ipaddress  # noqa: F401  (cryptography import check)
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        import pytest
        pytest.skip("cryptography not installed in this venv")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "qeos-client")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cert_path = tmp_path / "client.crt"
    key_path = tmp_path / "client.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def test_make_context_loads_a_client_certificate(tmp_path):
    cert, key = _self_signed(tmp_path)
    context = make_context(None, client_cert=cert, client_key=key)
    # Loading succeeded; a context with a client chain still verifies servers
    assert context.verify_mode.name == "CERT_REQUIRED"


def test_a_broken_client_certificate_is_a_config_error(tmp_path):
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate", encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        make_context(None, client_cert=str(bad))
    assert "--client-cert" in str(err.value)


def test_client_key_without_cert_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError) as err:
        make_context(None, client_key=str(tmp_path / "k.pem"))
    assert "--client-cert" in str(err.value)


def test_a_202_is_returned_not_raised(platform):
    platform.reply(202, {"discarded": True, "reason": "r"})

    status, body = send(collect(platform))
    assert (status, body["discarded"]) == (202, True)


STEP_PART = Part(body=json.dumps({"run": {}, "results": [{"name": "t", "status": "failed", "failed_step": {
    "text": "When I search Lisbon", "line": 4, "definition": "steps/search.js:12", "pattern": "When I search {…}"}}]},
    ensure_ascii=False, separators=(",", ":")).encode("utf-8"), idempotency_key="gh-1-1-step", count=1)
OLD_422 = {"detail": [{"type": "extra_forbidden", "loc": ["body", "results", 0, "failed_step", "definition"],
                       "msg": "Extra inputs are not permitted"}]}


def send_step(platform, warnings, part=STEP_PART):
    fake = FakeTime()
    return upload_part(collect(platform), KEY, part, None, sleep=fake.sleep, clock=fake.clock, rand=lambda: 0.0,
                       warn=warnings.append)


def test_an_older_platform_gets_the_upload_again_without_definition_and_pattern(platform):
    platform.reply(422, OLD_422)
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings) == (201, RECEIPT)
    first, second = (json.loads(r["body"]) for r in platform.requests)
    assert first["results"][0]["failed_step"]["definition"] == "steps/search.js:12"
    assert second["results"][0]["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-step"}
    assert len(warnings) == 1 and "older than this collector" in warnings[0]


def test_the_retry_without_the_fields_happens_once(platform):
    platform.reply(422, OLD_422)
    platform.reply(422, OLD_422)
    with pytest.raises(UploadError) as err:
        send_step(platform, [])
    assert len(platform.requests) == 2 and err.value.retryable is False


def test_a_5xx_after_the_downgrade_keeps_the_stripped_body(platform):
    platform.reply(422, OLD_422)
    platform.reply(503)
    platform.reply(201, RECEIPT)
    assert send_step(platform, [])[0] == 201
    assert all("definition" not in r["body"].decode() for r in platform.requests[1:])


def test_other_422s_are_not_retried(platform):
    platform.reply(422, {"detail": [{"type": "string_too_long", "loc": ["body", "results", 0, "name"], "msg": "x"}]})
    warnings = []
    with pytest.raises(UploadError):
        send_step(platform, warnings)
    assert len(platform.requests) == 1 and warnings == []


def test_a_422_that_is_not_json_is_not_retried(platform):
    platform.reply(422, b"<html>failed_step</html>")
    with pytest.raises(UploadError):
        send_step(platform, [])
    assert len(platform.requests) == 1


def test_a_part_without_the_fields_is_not_sent_again(platform):
    platform.reply(422, OLD_422)
    with pytest.raises(UploadError):
        send_step(platform, [], part=PART)
    assert len(platform.requests) == 1


def test_without_step_details_strips_only_the_two_fields():
    body = json.loads(upload.without_step_details(STEP_PART.body))
    assert body["results"][0]["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert upload.without_step_details(PART.body) is None
    assert upload.without_step_details(b"not json") is None


def test_a_422_about_another_failed_step_field_is_not_retried(platform):
    platform.reply(422, {"detail": [{"type": "string_too_long", "loc": ["body", "results", 0, "failed_step", "text"],
                                     "msg": "too long"}]})
    warnings = []
    with pytest.raises(UploadError):
        send_step(platform, warnings)
    assert len(platform.requests) == 1 and warnings == []


LOG_PART = Part(body=json.dumps({"run": {}, "results": [
    {"name": "t", "status": "passed", "log": 'INFO tripId="3960562"'},
    {"name": "u", "status": "passed"}]}).encode("utf-8"), idempotency_key="gh-1-1-log", count=2)
LOG_422 = {"detail": [{"type": "extra_forbidden", "loc": ["body", "results", 0, "log"],
                       "msg": "Extra inputs are not permitted"}]}


def test_an_older_platform_gets_the_upload_again_without_the_log(platform):
    platform.reply(422, LOG_422)
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings, part=LOG_PART) == (201, RECEIPT)
    first, second = (json.loads(r["body"]) for r in platform.requests)
    assert first["results"][0]["log"] == 'INFO tripId="3960562"'
    assert second["results"] == [{"name": "t", "status": "passed"}, {"name": "u", "status": "passed"}]
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-log"}
    assert len(warnings) == 1 and "log" in warnings[0] and "older than this collector" in warnings[0]


def test_a_platform_older_than_both_fields_gets_one_retry_without_either(platform):
    body = json.loads(STEP_PART.body)
    body["results"][0]["log"] = "INFO x"
    part = Part(body=json.dumps(body, ensure_ascii=False).encode("utf-8"), idempotency_key="gh-1-1-both", count=1)
    platform.reply(422, {"detail": OLD_422["detail"] + LOG_422["detail"]})
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings, part=part)[0] == 201
    second = json.loads(platform.requests[1]["body"])["results"][0]
    assert "log" not in second and second["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert len(platform.requests) == 2 and len(warnings) == 2


def test_the_retry_without_the_log_happens_once(platform):
    platform.reply(422, LOG_422)
    platform.reply(422, LOG_422)
    with pytest.raises(UploadError) as err:
        send_step(platform, [], part=LOG_PART)
    assert len(platform.requests) == 2 and err.value.retryable is False


def test_a_422_naming_the_log_of_a_part_without_one_is_not_retried(platform):
    platform.reply(422, LOG_422)
    with pytest.raises(UploadError):
        send_step(platform, [], part=PART)
    assert len(platform.requests) == 1


def test_a_422_about_something_else_keeps_the_log(platform):
    platform.reply(422, {"detail": [{"type": "string_too_long", "loc": ["body", "results", 0, "name"], "msg": "x"}]})
    with pytest.raises(UploadError):
        send_step(platform, [], part=LOG_PART)
    assert len(platform.requests) == 1


def test_without_log_strips_only_the_log():
    body = json.loads(upload.without_log(LOG_PART.body))
    assert body["results"] == [{"name": "t", "status": "passed"}, {"name": "u", "status": "passed"}]
    assert upload.without_log(PART.body) is None
    assert upload.without_log(b"not json") is None
