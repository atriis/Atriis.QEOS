from src.ingestion.core.config import settings
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import MemoryArtifactStore, get_artifact_store, screenshot_key


def test_memory_store_put_get_delete():
    store = MemoryArtifactStore()
    store.put("screenshots/1/a", b"one", "image/png")
    store.put("screenshots/1/b", b"two", "image/jpeg")
    assert store.get("screenshots/1/a") == b"one"
    assert store.objects["screenshots/1/b"] == (b"two", "image/jpeg")
    store.delete(["screenshots/1/a", "screenshots/1/missing"])
    assert list(store.objects) == ["screenshots/1/b"]


def test_delete_prefix_only_removes_that_project():
    store = MemoryArtifactStore()
    store.put("screenshots/1/a", b"x", "image/png")
    store.put("screenshots/1/b", b"x", "image/png")
    store.put("screenshots/10/a", b"x", "image/png")
    assert store.delete_prefix("screenshots/1/") == 2
    assert list(store.objects) == ["screenshots/10/a"]


def test_get_artifact_store_is_none_without_config(monkeypatch):
    artifact_store.reset()
    for name in ("ENDPOINT", "BUCKET", "ACCESS_KEY", "SECRET_KEY"):
        monkeypatch.setattr(settings, f"ARTIFACTS_S3_{name}", None)
    assert get_artifact_store() is None


def test_get_artifact_store_is_none_when_one_setting_is_missing(monkeypatch):
    artifact_store.reset()
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_BUCKET", "qeos-artifacts")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ACCESS_KEY", "key")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_SECRET_KEY", None)
    assert get_artifact_store() is None


def test_get_artifact_store_is_a_cached_s3_store_when_configured(monkeypatch):
    artifact_store.reset()
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_BUCKET", "qeos-artifacts")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ACCESS_KEY", "key")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_SECRET_KEY", "secret")
    store = get_artifact_store()
    assert isinstance(store, artifact_store.S3ArtifactStore)
    assert get_artifact_store() is store
    artifact_store.reset()


def test_screenshot_key():
    assert screenshot_key(7, "ab" * 32) == "screenshots/7/" + "ab" * 32
