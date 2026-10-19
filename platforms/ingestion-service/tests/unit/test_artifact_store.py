import pytest
from botocore.stub import Stubber

from src.ingestion.core.config import settings
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import (
    ArtifactDeleteError, ArtifactNotFound, MemoryArtifactStore, S3ArtifactStore, get_artifact_store, screenshot_key)


@pytest.fixture(autouse=True)
def _fresh_cache():
    artifact_store.reset()
    yield
    artifact_store.reset()


@pytest.fixture
def s3():
    store = S3ArtifactStore("http://minio:9000", "qeos-artifacts", "key", "secret")
    with Stubber(store._client) as stubber:
        yield store, stubber


def test_memory_store_put_get_delete():
    store = MemoryArtifactStore()
    store.put("screenshots/1/a", b"one", "image/png")
    store.put("screenshots/1/b", b"two", "image/jpeg")
    assert store.get("screenshots/1/a") == b"one"
    assert store.objects["screenshots/1/b"] == (b"two", "image/jpeg")
    store.delete(["screenshots/1/a", "screenshots/1/missing"])
    assert list(store.objects) == ["screenshots/1/b"]


def test_memory_store_get_of_a_missing_key_raises_not_found():
    with pytest.raises(ArtifactNotFound):
        MemoryArtifactStore().get("screenshots/1/missing")


def test_delete_prefix_only_removes_that_project():
    store = MemoryArtifactStore()
    store.put("screenshots/1/a", b"x", "image/png")
    store.put("screenshots/1/b", b"x", "image/png")
    store.put("screenshots/10/a", b"x", "image/png")
    assert store.delete_prefix("screenshots/1/") == 2
    assert list(store.objects) == ["screenshots/10/a"]


def test_get_artifact_store_is_none_without_config(monkeypatch):
    for name in ("ENDPOINT", "BUCKET", "ACCESS_KEY", "SECRET_KEY"):
        monkeypatch.setattr(settings, f"ARTIFACTS_S3_{name}", None)
    assert get_artifact_store() is None


def test_get_artifact_store_is_none_when_one_setting_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_BUCKET", "qeos-artifacts")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ACCESS_KEY", "key")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_SECRET_KEY", None)
    assert get_artifact_store() is None


def test_get_artifact_store_is_a_cached_s3_store_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_BUCKET", "qeos-artifacts")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ACCESS_KEY", "key")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_SECRET_KEY", "secret")
    store = get_artifact_store()
    assert isinstance(store, S3ArtifactStore)
    assert get_artifact_store() is store


def test_screenshot_key():
    assert screenshot_key(7, "ab" * 32) == "screenshots/7/" + "ab" * 32


def test_s3_put_sends_bucket_key_body_and_content_type(s3):
    store, stubber = s3
    stubber.add_response("put_object", {}, {
        "Bucket": "qeos-artifacts", "Key": "screenshots/1/a", "Body": b"img", "ContentType": "image/png"})
    store.put("screenshots/1/a", b"img", "image/png")
    stubber.assert_no_pending_responses()


def test_s3_get_of_a_missing_key_raises_not_found(s3):
    store, stubber = s3
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(ArtifactNotFound):
        store.get("screenshots/1/missing")


def test_s3_delete_sends_chunks_of_1000_keys(s3):
    store, stubber = s3
    keys = [f"screenshots/1/{i}" for i in range(2500)]
    for chunk in (keys[:1000], keys[1000:2000], keys[2000:]):
        stubber.add_response("delete_objects", {}, {
            "Bucket": "qeos-artifacts", "Delete": {"Objects": [{"Key": k} for k in chunk], "Quiet": True}})
    store.delete(keys)
    stubber.assert_no_pending_responses()


def test_s3_delete_raises_when_the_response_reports_errors(s3):
    store, stubber = s3
    stubber.add_response("delete_objects", {"Errors": [{"Key": "screenshots/1/a", "Code": "AccessDenied"}]})
    with pytest.raises(ArtifactDeleteError, match="AccessDenied"):
        store.delete(["screenshots/1/a", "screenshots/1/b"])


def test_s3_delete_prefix_pages_and_counts(s3):
    store, stubber = s3
    first = [f"screenshots/1/{i}" for i in range(3)]
    stubber.add_response("list_objects_v2", {
        "IsTruncated": True, "NextContinuationToken": "t", "Contents": [{"Key": k} for k in first]},
        {"Bucket": "qeos-artifacts", "Prefix": "screenshots/1/"})
    stubber.add_response("delete_objects", {})
    stubber.add_response("list_objects_v2", {
        "IsTruncated": False, "Contents": [{"Key": "screenshots/1/x"}]},
        {"Bucket": "qeos-artifacts", "Prefix": "screenshots/1/", "ContinuationToken": "t"})
    stubber.add_response("delete_objects", {})
    assert store.delete_prefix("screenshots/1/") == 4
    stubber.assert_no_pending_responses()
