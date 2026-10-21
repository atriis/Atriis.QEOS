"""HEAD|PUT /collect/artifacts/{sha256}: streamed, content-addressed trace upload (ADR-037)."""
import asyncio
import hashlib

import pytest

from src.ingestion.models import Blob, CollectionSettings
from src.ingestion.service import artifact_service
from src.ingestion.utils.artifact_store import MemoryArtifactStore, artifact_key, get_artifact_store
from tests.integration.test_pending_uploads import feed, row  # noqa: F401  the 410 test's project-service feed

ZIP = b"PK\x03\x04" + b"trace-bytes" * 100
OTHER_ZIP = b"PK\x03\x04" + b"another" * 50


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def url(data: bytes) -> str:
    return f"/api/v1/collect/artifacts/{sha(data)}"


@pytest.fixture
def store(client):
    from src.ingestion.api.main import app

    memory = MemoryArtifactStore()
    app.dependency_overrides[get_artifact_store] = lambda: memory
    return memory


@pytest.fixture
def headers(db, make_key):
    _, key = make_key(project_id=7)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=False, keep_traces=True,
                              trace_days=14, discarded_count=0))
    db.commit()
    return {"Authorization": f"Bearer {key}"}


def put(client, headers, data=ZIP, media_type="application/zip", path=None, **kwargs):
    return client.put(path or url(data), content=data, headers={**headers, "Content-Type": media_type}, **kwargs)


def nothing_left(store, db):
    """No object anywhere (final key or temporary one) and no blob row."""
    return store.objects == {} and db.query(Blob).count() == 0


def test_put_then_head_200(client, store, headers, db):
    assert client.head(url(ZIP), headers=headers).status_code == 404
    response = put(client, headers)
    assert response.status_code == 201, response.text
    assert response.json() == {"sha256": sha(ZIP)}
    assert client.head(url(ZIP), headers=headers).status_code == 200
    row_ = db.query(Blob).one()
    assert (row_.project_id, row_.sha256, row_.kind, row_.media_type, row_.bytes) == (
        7, sha(ZIP), "trace", "application/zip", len(ZIP))
    # Only the content-addressed object remains: the temporary one is gone
    assert set(store.objects) == {artifact_key(7, sha(ZIP))}
    assert store.objects[artifact_key(7, sha(ZIP))] == (ZIP, "application/zip")


def test_head_ignores_a_screenshot_blob_of_that_hash(client, store, headers, db):
    db.add(Blob(project_id=7, sha256=sha(ZIP), media_type="image/png", bytes=1, kind="screenshot"))
    db.commit()
    assert client.head(url(ZIP), headers=headers).status_code == 404


def test_second_put_is_200_and_stores_once(client, store, headers, db):
    assert put(client, headers).status_code == 201
    copies = []
    original = store.copy
    store.copy = lambda *args: (copies.append(args), original(*args))
    response = put(client, headers)
    assert response.status_code == 200, response.text
    assert copies == []
    assert db.query(Blob).count() == 1
    assert set(store.objects) == {artifact_key(7, sha(ZIP))}  # the second upload's temporary object is deleted


def test_a_concurrent_duplicate_row_is_200_not_500(client, store, headers, db, monkeypatch):
    """Two uploads of one trace at once: both pass the existence check, one row is written, neither fails."""
    monkeypatch.setattr(artifact_service, "find_trace", lambda *args: None)
    assert put(client, headers).status_code == 201
    assert put(client, headers).status_code == 200
    assert db.query(Blob).count() == 1
    assert set(store.objects) == {artifact_key(7, sha(ZIP))}


def test_wrong_sha_400_and_nothing_left(client, store, headers, db):
    response = put(client, headers, ZIP, path=url(OTHER_ZIP))
    assert response.status_code == 400
    assert nothing_left(store, db)


def test_not_a_zip_400_and_nothing_left(client, store, headers, db):
    data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 10
    assert put(client, headers, data).status_code == 400
    assert nothing_left(store, db)


def test_a_body_shorter_than_the_magic_is_400(client, store, headers, db):
    assert put(client, headers, b"PK").status_code == 400
    assert nothing_left(store, db)


def test_wrong_content_type_400(client, store, headers, db):
    assert put(client, headers, ZIP, "application/octet-stream").status_code == 400
    assert nothing_left(store, db)


def test_a_body_shorter_than_declared_is_400_and_nothing_left(client, store, headers, db):
    """The client declares more bytes than it sends: the hash of what arrived cannot be trusted as the file."""
    def body():
        yield ZIP[:100]

    response = client.put(url(ZIP), content=body(), headers={
        **headers, "Content-Type": "application/zip", "Content-Length": str(len(ZIP))})
    assert response.status_code == 400
    assert nothing_left(store, db)


def test_a_stream_that_fails_midway_leaves_nothing(client, store, headers, db):
    def body():
        yield ZIP[:100]
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        client.put(url(ZIP), content=body(), headers={**headers, "Content-Type": "application/zip"})
    assert nothing_left(store, db)


def test_a_client_disconnect_midway_leaves_nothing(client, store, headers, db):
    """What a server sees when the client drops the connection: an http.disconnect message mid-body."""
    from src.ingestion.api.main import app

    messages = [{"type": "http.request", "body": ZIP[:100], "more_body": True}, {"type": "http.disconnect"}]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    path = url(ZIP)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"authorization", headers["Authorization"].encode()), (b"content-type", b"application/zip")],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 400
    assert nothing_left(store, db)


def test_temporary_object_is_used_while_streaming(client, store, headers, db):
    """The unverified body never lands on the content-addressed key."""
    keys = []
    original = store.put_stream

    async def spy(key, chunks, media_type):
        keys.append(key)
        await original(key, chunks, media_type)

    store.put_stream = spy
    assert put(client, headers).status_code == 201
    assert len(keys) == 1 and keys[0].startswith("artifacts/7/incoming/") and keys[0] != artifact_key(7, sha(ZIP))


def test_a_failing_temp_delete_still_answers_400(client, store, headers, db):
    def broken(keys):
        raise RuntimeError("store down")

    store.delete = broken
    assert put(client, headers, ZIP, path=url(OTHER_ZIP)).status_code == 400
    assert db.query(Blob).count() == 0
    assert artifact_key(7, sha(OTHER_ZIP)) not in store.objects


def test_the_cap_is_100_mb():
    assert artifact_service.MAX_TRACE_BYTES == 104857600


def test_declared_length_over_100mb_is_413_before_reading(client, store, headers, db):
    read = []

    def body():
        read.append(True)
        yield ZIP

    response = client.put(url(ZIP), content=body(), headers={
        **headers, "Content-Type": "application/zip", "Content-Length": str(104857600 + 1)})
    assert response.status_code == 413
    assert read == []  # refused on the header alone
    assert nothing_left(store, db)


def test_a_chunked_body_over_the_cap_is_413_and_nothing_left(client, store, headers, db, monkeypatch):
    """No declared length: the cap is applied while streaming, before the object is completed."""
    monkeypatch.setattr(artifact_service, "MAX_TRACE_BYTES", 1000)
    big = ZIP + b"0" * 1000

    def body():
        for start in range(0, len(big), 300):
            yield big[start:start + 300]

    response = client.put(url(big), content=body(), headers={**headers, "Content-Type": "application/zip"})
    assert response.status_code == 413
    assert nothing_left(store, db)


def test_exactly_the_cap_is_stored(client, store, headers, db, monkeypatch):
    monkeypatch.setattr(artifact_service, "MAX_TRACE_BYTES", len(ZIP))
    assert put(client, headers).status_code == 201


def test_keep_traces_off_403(client, store, headers, db):
    db.query(CollectionSettings).update({"keep_traces": False})
    db.commit()
    response = put(client, headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "traces_off"
    assert nothing_left(store, db)


def test_screenshots_on_does_not_allow_traces(client, store, headers, db):
    db.query(CollectionSettings).update({"keep_traces": False, "keep_screenshots": True})
    db.commit()
    assert put(client, headers).status_code == 403


def test_no_store_403(client, headers):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: None
    assert put(client, headers).status_code == 403


def test_pending_deletion_410(client, store, make_key, db, feed):  # noqa: F811
    feed(row(7, True))
    _, key = make_key(project_id=7)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=False, keep_traces=True,
                              trace_days=14, discarded_count=0))
    db.commit()
    response = put(client, {"Authorization": f"Bearer {key}"})
    assert response.status_code == 410
    assert nothing_left(store, db)


def test_another_projects_trace_is_404_on_head(client, store, headers, make_key):
    assert put(client, headers).status_code == 201
    _, other = make_key(project_id=8)
    assert client.head(url(ZIP), headers={"Authorization": f"Bearer {other}"}).status_code == 404


def test_a_malformed_hash_is_404(client, store, headers):
    assert client.head("/api/v1/collect/artifacts/ABC", headers=headers).status_code == 404
    assert client.put("/api/v1/collect/artifacts/" + "G" * 64, content=ZIP,
                      headers={**headers, "Content-Type": "application/zip"}).status_code == 404


def test_artifacts_need_a_key(client, store):
    assert client.head(url(ZIP)).status_code == 401
    assert client.put(url(ZIP), content=ZIP, headers={"Content-Type": "application/zip"}).status_code == 401


KEY_URL = "/api/v1/collect/key"


def test_key_check_reports_artifacts(client, make_key, db):
    from src.ingestion.api.main import app

    _, key = make_key(project_id=7)
    auth = {"Authorization": f"Bearer {key}"}
    app.dependency_overrides[get_artifact_store] = lambda: MemoryArtifactStore()
    assert client.get(KEY_URL, headers=auth).json()["artifacts"] is False  # store, switch off (no settings row)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, keep_traces=False,
                              trace_days=14, discarded_count=0))
    db.commit()
    assert client.get(KEY_URL, headers=auth).json()["artifacts"] is False  # screenshots alone are not traces
    db.query(CollectionSettings).update({"keep_traces": True})
    db.commit()
    assert client.get(KEY_URL, headers=auth).json()["artifacts"] is True
    app.dependency_overrides[get_artifact_store] = lambda: None
    assert client.get(KEY_URL, headers=auth).json()["artifacts"] is False  # switch on, no store
