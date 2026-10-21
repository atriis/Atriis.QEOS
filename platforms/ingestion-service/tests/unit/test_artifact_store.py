import asyncio
import io

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from src.ingestion.core.config import settings
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import (
    ArtifactDeleteError, ArtifactNotFound, ArtifactRangeError, MemoryArtifactStore, S3ArtifactStore, artifact_key, get_artifact_store, screenshot_key)


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


def test_artifact_key():
    assert artifact_key(3, "ab" * 32) == "artifacts/3/" + "ab" * 32


def test_memory_store_put_stream_then_open_and_get_range():
    store = MemoryArtifactStore()
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"01", b"234", b"56789"]), "application/zip"))
    assert store.objects["artifacts/1/a"] == (b"0123456789", "application/zip")
    chunks, size = store.open("artifacts/1/a")
    assert size == 10 and b"".join(chunks) == b"0123456789"
    assert store.get_range("artifacts/1/a", 2, 5) == b"2345"  # end is inclusive, as in an HTTP Range


def test_memory_store_put_stream_takes_an_async_iterator():
    async def chunks():
        yield b"ab"
        yield b"cd"

    store = MemoryArtifactStore()
    asyncio.run(store.put_stream("artifacts/1/b", chunks(), "application/zip"))
    assert store.get("artifacts/1/b") == b"abcd"


def test_memory_store_open_and_range_of_a_missing_key_raise_not_found():
    with pytest.raises(ArtifactNotFound):
        MemoryArtifactStore().open("artifacts/1/missing")
    with pytest.raises(ArtifactNotFound):
        MemoryArtifactStore().get_range("artifacts/1/missing", 0, 1)


# S3 streaming (ADR-037). The Stubber checks each call's parameters, so a wrong part split fails the test.
BUCKET = "qeos-artifacts"


def _create(stubber, key):
    stubber.add_response("create_multipart_upload", {"UploadId": "u1"},
                         {"Bucket": BUCKET, "Key": key, "ContentType": "application/zip"})


def _upload(stubber, key, bodies):
    _create(stubber, key)
    for number, body in enumerate(bodies, 1):
        stubber.add_response("upload_part", {"ETag": f"e{number}"},
                             {"Bucket": BUCKET, "Key": key, "UploadId": "u1", "PartNumber": number, "Body": body})


def _complete(stubber, key, count):
    stubber.add_response("complete_multipart_upload", {}, {
        "Bucket": BUCKET, "Key": key, "UploadId": "u1",
        "MultipartUpload": {"Parts": [{"ETag": f"e{n}", "PartNumber": n} for n in range(1, count + 1)]}})


def _abort(stubber, key):
    stubber.add_response("abort_multipart_upload", {}, {"Bucket": BUCKET, "Key": key, "UploadId": "u1"})


def test_s3_put_stream_splits_into_parts_and_keeps_a_short_last_part(s3, monkeypatch):
    store, stubber = s3
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    _upload(stubber, "artifacts/1/a", [b"0123", b"4567", b"89"])
    _complete(stubber, "artifacts/1/a", 3)
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"01", b"23456", b"789"]), "application/zip"))
    stubber.assert_no_pending_responses()


def test_s3_put_stream_of_an_exact_multiple_has_no_empty_trailing_part(s3, monkeypatch):
    store, stubber = s3
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    _upload(stubber, "artifacts/1/a", [b"0123", b"4567"])
    _complete(stubber, "artifacts/1/a", 2)
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"01234567"]), "application/zip"))
    stubber.assert_no_pending_responses()


def test_s3_put_stream_of_an_empty_body_sends_one_empty_part(s3):
    store, stubber = s3
    _upload(stubber, "artifacts/1/a", [b""])
    _complete(stubber, "artifacts/1/a", 1)
    asyncio.run(store.put_stream("artifacts/1/a", iter([]), "application/zip"))
    stubber.assert_no_pending_responses()


def test_s3_put_stream_aborts_and_reraises_when_a_part_fails(s3, monkeypatch):
    store, stubber = s3
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    _create(stubber, "artifacts/1/a")
    stubber.add_client_error("upload_part", service_error_code="InternalError", http_status_code=500)
    _abort(stubber, "artifacts/1/a")
    with pytest.raises(ClientError) as raised:
        asyncio.run(store.put_stream("artifacts/1/a", iter([b"01234567"]), "application/zip"))
    assert raised.value.response["Error"]["Code"] == "InternalError"
    stubber.assert_no_pending_responses()


def test_s3_put_stream_aborts_and_reraises_when_the_iterator_fails(s3):
    store, stubber = s3

    async def chunks():
        yield b"01"
        raise ValueError("client went away")

    _create(stubber, "artifacts/1/a")
    _abort(stubber, "artifacts/1/a")
    with pytest.raises(ValueError, match="client went away"):
        asyncio.run(store.put_stream("artifacts/1/a", chunks(), "application/zip"))
    stubber.assert_no_pending_responses()


def test_s3_put_stream_keeps_the_original_error_when_the_abort_fails_too(s3):
    store, stubber = s3

    async def chunks():
        raise ValueError("original")
        yield b""  # pragma: no cover

    _create(stubber, "artifacts/1/a")
    stubber.add_client_error("abort_multipart_upload", service_error_code="InternalError", http_status_code=500)
    with pytest.raises(ValueError, match="original"):
        asyncio.run(store.put_stream("artifacts/1/a", chunks(), "application/zip"))
    stubber.assert_no_pending_responses()


def test_s3_open_streams_the_body_and_reports_its_size(s3):
    store, stubber = s3
    body = StreamingBody(io.BytesIO(b"0123456789"), 10)
    stubber.add_response("get_object", {"Body": body, "ContentLength": 10}, {"Bucket": BUCKET, "Key": "artifacts/1/a"})
    chunks, size = store.open("artifacts/1/a")
    assert size == 10 and b"".join(chunks) == b"0123456789"


def test_s3_get_range_sends_an_inclusive_range(s3):
    store, stubber = s3
    body = StreamingBody(io.BytesIO(b"2345"), 4)
    stubber.add_response("get_object", {"Body": body},
                         {"Bucket": BUCKET, "Key": "artifacts/1/a", "Range": "bytes=2-5"})
    assert store.get_range("artifacts/1/a", 2, 5) == b"2345"


def test_s3_open_and_get_range_of_a_missing_key_raise_not_found(s3):
    store, stubber = s3
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(ArtifactNotFound):
        store.open("artifacts/1/missing")
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(ArtifactNotFound):
        store.get_range("artifacts/1/missing", 0, 1)


def test_s3_get_range_past_the_end_raises_range_error(s3):
    store, stubber = s3
    stubber.add_client_error("get_object", service_error_code="InvalidRange", http_status_code=416)
    with pytest.raises(ArtifactRangeError):
        store.get_range("artifacts/1/a", 100, 200)


@pytest.mark.parametrize("start,end", [(10, 12), (11, 20), (5, 4)])
def test_memory_store_get_range_outside_the_object_raises_range_error(start, end):
    """As S3's InvalidRange: a start at or past the end, or an end before the start."""
    store = MemoryArtifactStore()
    store.put("artifacts/1/a", b"0123456789", "application/zip")
    with pytest.raises(ArtifactRangeError):
        store.get_range("artifacts/1/a", start, end)
    assert store.get_range("artifacts/1/a", 8, 99) == b"89"  # an end past the object is cut, as S3 does


def test_memory_store_copy():
    store = MemoryArtifactStore()
    store.put("artifacts/1/incoming/x", b"zip", "application/zip")
    store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    assert store.objects["artifacts/1/abc"] == (b"zip", "application/zip")
    assert "artifacts/1/incoming/x" in store.objects  # a copy, the caller deletes the source
    with pytest.raises(ArtifactNotFound):
        store.copy("artifacts/1/missing", "artifacts/1/def")


def test_s3_copy_sends_source_and_destination(s3):
    store, stubber = s3
    stubber.add_response("copy_object", {}, {
        "Bucket": BUCKET, "Key": "artifacts/1/abc",
        "CopySource": {"Bucket": BUCKET, "Key": "artifacts/1/incoming/x"}})
    store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    stubber.assert_no_pending_responses()
