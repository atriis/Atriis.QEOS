"""One-time links for the trace viewer (ADR-037, stage 2): the self-hosted viewer fetches the trace without the Bearer
token, so a reader asks for a link valid 60 s, bound to the artifact, the user and the client address."""
import hashlib
import logging
from datetime import timedelta

import pytest

from src.ingestion.models import ArtifactLink, ResultArtifact
from src.ingestion.service import artifact_link_service
from src.ingestion.utils.artifact_store import artifact_key
from tests.integration.test_traces_runs import SHA, T0, ZIP, add_trace, result_of, store  # noqa: F401 (fixture)

IP = "203.0.113.5"
OTHER_IP = "198.51.100.7"
ZIP_B = b"PK\x03\x04" + b"B" * 300
SHA_B = hashlib.sha256(ZIP_B).hexdigest()
NOT_FOUND = {"detail": "Not found"}


@pytest.fixture
def clock(monkeypatch):
    """The links' clock (the database's), moved by the tests."""
    now = {"at": T0}
    monkeypatch.setattr(artifact_link_service, "db_now", lambda db: now["at"])
    return now


@pytest.fixture
def trace_row(project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    return row


def make_link(client, auth, artifact_id, project_id=1, ip=IP, user_id=1):
    return client.post(f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/link",
                       headers={**auth(user_id), "X-Forwarded-For": ip})


def token_of(resp):
    assert resp.status_code == 201, resp.text
    url = resp.json()["url"]
    assert url.startswith("/api/v1/artifact-links/")
    return url.rsplit("/", 1)[1]


def fetch(client, token, ip=IP, method="GET", **headers):
    return client.request(method, f"/api/v1/artifact-links/{token}", headers={"X-Forwarded-For": ip, **headers})


def test_link_serves_the_trace_with_ranges_within_its_60_seconds(client, auth, trace_row, clock):
    token = token_of(make_link(client, auth, trace_row.id))
    clock["at"] = T0 + timedelta(seconds=59)
    whole = fetch(client, token)
    assert whole.status_code == 200 and whole.content == ZIP
    assert whole.headers["content-type"] == "application/zip"
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.headers["cache-control"] == "private, no-store"
    assert whole.headers["x-content-type-options"] == "nosniff"
    # The viewer reads parts of the zip: several requests, each one range, within the 60 s
    part = fetch(client, token, Range="bytes=4-9")
    assert part.status_code == 206 and part.content == ZIP[4:10]
    assert part.headers["content-range"] == f"bytes 4-9/{len(ZIP)}"
    tail = fetch(client, token, Range="bytes=-22")
    assert tail.status_code == 206 and tail.content == ZIP[-22:]
    assert fetch(client, token, Range="bytes=5000-").status_code == 416
    assert fetch(client, token).content == ZIP


def test_link_expires_after_60_seconds(client, auth, trace_row, clock):
    resp = make_link(client, auth, trace_row.id)
    assert resp.json()["expires_at"] == (T0 + timedelta(seconds=60)).isoformat()
    token = token_of(resp)
    clock["at"] = T0 + timedelta(seconds=61)
    expired = fetch(client, token)
    assert expired.status_code == 404 and expired.json() == NOT_FOUND
    assert fetch(client, token, Range="bytes=0-3").status_code == 404
    clock["at"] = T0 + timedelta(seconds=60)  # the end itself is outside
    assert fetch(client, token).status_code == 404


def test_link_from_another_address_is_404(client, auth, trace_row, clock):
    token = token_of(make_link(client, auth, trace_row.id))
    other = fetch(client, token, ip=OTHER_IP)
    assert other.status_code == 404 and other.json() == NOT_FOUND
    # Without X-Forwarded-For the socket peer counts ("testclient" in tests), not the address of the link
    assert client.get(f"/api/v1/artifact-links/{token}").status_code == 404
    # A list in X-Forwarded-For: only its first entry counts, which the gateway writes
    assert fetch(client, token, ip=f"{OTHER_IP}, {IP}").status_code == 404
    assert fetch(client, token, ip=f"{IP}, {OTHER_IP}").status_code == 200


@pytest.mark.parametrize("token", ["x" * 43, "A" * 43, "short", "a" * 200, "%2e%2e"])
def test_unknown_or_malformed_token_is_404(client, trace_row, clock, token):
    resp = fetch(client, token)
    assert resp.status_code == 404 and resp.json() == NOT_FOUND


def test_a_link_to_a_deleted_artifact_is_404(client, auth, trace_row, clock, db):
    token = token_of(make_link(client, auth, trace_row.id))
    db.query(ResultArtifact).filter_by(id=trace_row.id).delete()
    db.commit()
    resp = fetch(client, token)
    assert resp.status_code == 404 and resp.json() == NOT_FOUND


def test_a_link_whose_object_is_missing_is_404_like_the_rest(client, auth, trace_row, clock, store):
    token = token_of(make_link(client, auth, trace_row.id))
    store.delete([artifact_key(1, SHA)])
    resp = fetch(client, token)
    assert resp.status_code == 404 and resp.json() == NOT_FOUND


def test_a_token_for_trace_a_never_serves_trace_b(client, auth, trace_row, clock, db, store):
    row_b = add_trace(db, _result(db, trace_row), sha=SHA_B, position=1, name="b", size=len(ZIP_B))
    store.put(artifact_key(1, SHA_B), ZIP_B, "application/zip")
    token_a = token_of(make_link(client, auth, trace_row.id))
    token_b = token_of(make_link(client, auth, row_b.id))
    assert token_a != token_b
    assert fetch(client, token_a).content == ZIP
    assert fetch(client, token_b).content == ZIP_B
    assert fetch(client, token_a, Range="bytes=0-9").content == ZIP[:10]


def _result(db, row):
    from src.ingestion.models import RunResult

    return db.get(RunResult, row.result_id)


def test_a_non_member_cannot_create_a_link(client, auth, project_role, seed_run, db, store):
    """Review Focus 3: the link is created with the user's own access, as the download."""
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    project_role(status_code=404)
    assert make_link(client, auth, row.id).status_code == 404
    assert client.post(f"/api/v1/projects/1/artifacts/{row.id}/link").status_code == 401
    assert db.query(ArtifactLink).count() == 0


def test_no_link_to_an_artifact_of_another_project(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    other = add_trace(db, result_of(db, seed_run(T0, project_id=2)), project_id=2)
    store.put(artifact_key(2, SHA), ZIP, "application/zip")
    assert make_link(client, auth, other.id).status_code == 404
    assert make_link(client, auth, 99999).status_code == 404
    assert db.query(ArtifactLink).count() == 0


def test_the_stored_token_is_its_hash_only(client, auth, trace_row, clock, db):
    token = token_of(make_link(client, auth, trace_row.id, user_id=7))
    assert len(token) == 43  # secrets.token_urlsafe(32): 32 random bytes
    link = db.query(ArtifactLink).one()
    assert link.token_sha256 == hashlib.sha256(token.encode("ascii")).hexdigest()
    assert (link.artifact_id, link.user_id, link.client_ip) == (trace_row.id, 7, IP)
    stored = [str(getattr(link, column.name)) for column in ArtifactLink.__table__.columns]
    assert not any(token in value for value in stored)


def test_each_link_is_a_new_token(client, auth, trace_row, clock):
    first = token_of(make_link(client, auth, trace_row.id))
    second = token_of(make_link(client, auth, trace_row.id))
    assert first != second
    assert fetch(client, first).status_code == 200 and fetch(client, second).status_code == 200


def test_head_answers_the_headers_without_a_body(client, auth, trace_row, clock, store):
    token = token_of(make_link(client, auth, trace_row.id))
    store.open = lambda key: pytest.fail("HEAD must not read the object")
    resp = fetch(client, token, method="HEAD")
    assert resp.status_code == 200 and resp.content == b""
    assert resp.headers["content-length"] == str(len(ZIP))
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["cache-control"] == "private, no-store"
    assert fetch(client, token, ip=OTHER_IP, method="HEAD").status_code == 404
    clock["at"] = T0 + timedelta(seconds=61)
    assert fetch(client, token, method="HEAD").status_code == 404


def test_the_link_holds_no_transaction_while_reading(client, auth, trace_row, clock, db, store):
    token = token_of(make_link(client, auth, trace_row.id))
    seen = []
    original = store.open
    store.open = lambda key: (seen.append(db.in_transaction()), original(key))[1]
    assert fetch(client, token).status_code == 200
    assert seen == [False]


def test_the_access_log_never_shows_the_token():
    from src.ingestion.api.main import ACCESS_LOG_FILTER

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", "/api/v1/artifact-links/SECRETtoken_-x?a=1", "1.1", 200), None)
    assert ACCESS_LOG_FILTER.filter(record) is True
    assert "SECRET" not in record.getMessage()
    assert "/api/v1/artifact-links/***" in record.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                              ("1.2.3.4:5", "GET", "/api/v1/runs/3", "1.1", 200), None)
    assert ACCESS_LOG_FILTER.filter(other) is True and "/api/v1/runs/3" in other.getMessage()
    assert ACCESS_LOG_FILTER in logging.getLogger("uvicorn.access").filters


def test_delete_expired_removes_only_expired_links(client, auth, trace_row, clock, db):
    token_of(make_link(client, auth, trace_row.id))
    clock["at"] = T0 + timedelta(seconds=30)
    token_of(make_link(client, auth, trace_row.id))
    now = T0 + timedelta(seconds=61)
    assert artifact_link_service.delete_expired(db, now, dry_run=True) == 1
    assert db.query(ArtifactLink).count() == 2
    assert artifact_link_service.delete_expired(db, now, dry_run=False) == 1
    db.expire_all()
    assert db.query(ArtifactLink).count() == 1


def test_creating_a_link_deletes_the_expired_ones(client, auth, trace_row, clock, db):
    token_of(make_link(client, auth, trace_row.id))
    clock["at"] = T0 + timedelta(seconds=30)
    live = token_of(make_link(client, auth, trace_row.id))
    clock["at"] = T0 + timedelta(seconds=61)  # the first has expired, the second has not
    newest = token_of(make_link(client, auth, trace_row.id))
    db.expire_all()
    hashes = {link.token_sha256 for link in db.query(ArtifactLink)}
    assert hashes == {hashlib.sha256(t.encode("ascii")).hexdigest() for t in (live, newest)}


def test_each_use_is_audited_without_the_token(client, auth, trace_row, clock, caplog):
    artifact_id = trace_row.id  # read before the requests: the endpoint closes the shared session
    token = token_of(make_link(client, auth, artifact_id, user_id=7))
    with caplog.at_level(logging.INFO, logger="src.ingestion.api.v1.endpoints.artifacts"):
        assert fetch(client, token).status_code == 200
        assert fetch(client, token, method="HEAD").status_code == 200
        assert fetch(client, token, ip=OTHER_IP).status_code == 404
    used = [r.getMessage() for r in caplog.records if "artifact link used" in r.getMessage()]
    assert used == [f"artifact link used: user_id=7 artifact_id={artifact_id} ip={IP}"] * 2
    assert not any(token in r.getMessage() for r in caplog.records)


def test_links_read_the_database_clock_not_the_replicas(db):
    """Create and check read the same clock, the database's, so two replicas with skewed clocks agree on a link's
    60 s. Unpatched here: the real clock, as an aware UTC time."""
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    now = artifact_link_service.db_now(db)
    assert now.tzinfo is not None
    assert before <= now <= datetime.now(timezone.utc) + timedelta(seconds=5)
