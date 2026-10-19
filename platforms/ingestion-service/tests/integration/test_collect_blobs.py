"""HEAD|PUT /collect/blobs/{sha256}: content-addressed screenshot upload (ADR-036)."""
import hashlib

import pytest

from src.ingestion.models import Blob, CollectionSettings
from src.ingestion.utils.artifact_store import MemoryArtifactStore, get_artifact_store, screenshot_key

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 10
JPEG = b"\xff\xd8\xff\xe0" + b"pixels" * 10
WEBP = b"RIFF\x10\x00\x00\x00WEBP" + b"pixels" * 10


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def url(data: bytes) -> str:
    return f"/api/v1/collect/blobs/{sha(data)}"


@pytest.fixture
def store(client):
    from src.ingestion.api.main import app

    memory = MemoryArtifactStore()
    app.dependency_overrides[get_artifact_store] = lambda: memory
    return memory


@pytest.fixture
def headers(db, make_key):
    _, key = make_key(project_id=7)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, discarded_count=0))
    db.commit()
    return {"Authorization": f"Bearer {key}"}


def put(client, headers, data=PNG, media_type="image/png", path=None):
    return client.put(path or url(data), content=data, headers={**headers, "Content-Type": media_type})


def test_put_then_head_200(client, store, headers, db):
    assert client.head(url(PNG), headers=headers).status_code == 404
    response = put(client, headers)
    assert response.status_code == 201, response.text
    assert client.head(url(PNG), headers=headers).status_code == 200
    row = db.query(Blob).one()
    assert (row.project_id, row.sha256, row.media_type, row.bytes) == (7, sha(PNG), "image/png", len(PNG))
    assert store.get(screenshot_key(7, sha(PNG))) == PNG


@pytest.mark.parametrize("data,media_type", [(JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_put_accepts_jpeg_and_webp(client, store, headers, data, media_type):
    assert put(client, headers, data, media_type).status_code == 201


def test_put_twice_stores_once(client, store, headers, db):
    assert put(client, headers).status_code == 201
    calls = []
    original = store.put
    store.put = lambda *args: (calls.append(args), original(*args))
    assert put(client, headers).status_code == 200
    assert calls == []
    assert db.query(Blob).count() == 1


def test_put_hash_mismatch_400(client, store, headers, db):
    response = put(client, headers, PNG, path=url(JPEG))
    assert response.status_code == 400
    assert db.query(Blob).count() == 0 and store.objects == {}


def test_put_png_bytes_as_jpeg_400(client, store, headers):
    assert put(client, headers, PNG, "image/jpeg").status_code == 400


def test_put_unsupported_type_400(client, store, headers):
    assert put(client, headers, PNG, "image/gif").status_code == 400


def test_put_over_5mb_413(client, store, headers):
    big = PNG + b"0" * (5 * 1024 * 1024)
    assert put(client, headers, big).status_code == 413
    assert store.objects == {}


def test_put_exactly_5mb_is_stored(client, store, headers):
    data = PNG + b"0" * (5 * 1024 * 1024 - len(PNG))
    assert put(client, headers, data).status_code == 201


def test_put_when_setting_off_403(client, store, headers, db):
    db.query(CollectionSettings).update({"keep_screenshots": False})
    db.commit()
    assert put(client, headers).status_code == 403
    assert store.objects == {}


def test_put_when_no_store_403(client, headers):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: None
    assert put(client, headers).status_code == 403


def test_head_other_projects_blob_404(client, store, headers, make_key):
    assert put(client, headers).status_code == 201
    _, other = make_key(project_id=8)
    assert client.head(url(PNG), headers={"Authorization": f"Bearer {other}"}).status_code == 404


def test_a_malformed_hash_is_404(client, store, headers):
    assert client.head("/api/v1/collect/blobs/ABC", headers=headers).status_code == 404
    assert client.put("/api/v1/collect/blobs/" + "G" * 64, content=PNG,
                      headers={**headers, "Content-Type": "image/png"}).status_code == 404


def test_blobs_need_a_key(client, store):
    assert client.head(url(PNG)).status_code == 401
    assert client.put(url(PNG), content=PNG, headers={"Content-Type": "image/png"}).status_code == 401

