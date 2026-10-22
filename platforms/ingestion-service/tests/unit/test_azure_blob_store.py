"""AzureBlobArtifactStore (ADR-038) against a mocked ContainerClient, mirroring the S3 store's tests."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from src.ingestion.core.config import settings
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import (
    ArtifactDeleteError, ArtifactNotFound, ArtifactRangeError, S3ArtifactStore, get_artifact_store)
from src.ingestion.utils.azure_blob_store import AzureBlobArtifactStore

ACCOUNT_URL = "https://qeosartifacts.blob.core.windows.net"
CONTAINER = "qeos-artifacts"


@pytest.fixture(autouse=True)
def _fresh_cache():
    artifact_store.reset()
    yield
    artifact_store.reset()


@pytest.fixture
def made(monkeypatch):
    """Every ContainerClient the store builds, as mocks, and the credential it was given."""
    clients = []

    def container_client(**kwargs):
        client = MagicMock(name=f"container{len(clients)}")
        client.made_with = kwargs
        clients.append(client)
        return client

    credential = MagicMock(name="DefaultAzureCredential")
    monkeypatch.setattr("azure.storage.blob.ContainerClient", container_client)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", credential)
    return SimpleNamespace(clients=clients, credential=credential)


@pytest.fixture
def azure(made):
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    return store, made.clients[0]


def http_error(status: int, code: str) -> HttpResponseError:
    error = HttpResponseError(message=code)
    error.status_code = status
    error.error_code = code
    return error


def not_found() -> ResourceNotFoundError:
    error = ResourceNotFoundError(message="BlobNotFound")
    error.status_code = 404
    error.error_code = "BlobNotFound"
    return error


def downloader(data: bytes) -> MagicMock:
    download = MagicMock(name="StorageStreamDownloader")
    download.size = len(data)
    download.readall.return_value = data
    download.chunks.return_value = iter([data[:3], data[3:]] if data else [])
    return download


# Construction: workload identity, timeouts as the S3 store's

def test_builds_its_clients_with_default_azure_credential_and_short_timeouts(made):
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    made.credential.assert_called_once_with()
    client, copy_client = made.clients
    assert store._container is client and store._copy_container is copy_client
    for each in (client, copy_client):
        assert each.made_with["account_url"] == ACCOUNT_URL
        assert each.made_with["container_name"] == CONTAINER
        assert each.made_with["credential"] is made.credential.return_value
        assert each.made_with["connection_timeout"] == 5
        retry = each.made_with["retry_policy"]  # one retry, a second apart: not the SDK's 3 starting 15 s apart
        assert retry.total_retries == 1 and retry.initial_backoff == 1
        # a streamed read holds at most one chunk, never a whole trace
        assert each.made_with["max_single_get_size"] <= 4 * 1024 * 1024
        assert each.made_with["max_chunk_get_size"] <= 4 * 1024 * 1024
    assert client.made_with["read_timeout"] == 10
    assert copy_client.made_with["read_timeout"] == artifact_store.COPY_READ_TIMEOUT == 60


def test_takes_another_credential_when_given_one(made):
    AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER, credential="azurite-key")
    made.credential.assert_not_called()
    assert made.clients[0].made_with["credential"] == "azurite-key"


# put / get

def test_put_overwrites_the_blob_with_its_content_type(azure):
    store, client = azure
    store.put("screenshots/1/a", b"img", "image/png")
    client.upload_blob.assert_called_once()
    kwargs = client.upload_blob.call_args.kwargs
    assert kwargs["name"] == "screenshots/1/a" and kwargs["data"] == b"img" and kwargs["overwrite"] is True
    assert kwargs["content_settings"].content_type == "image/png"


def test_get_reads_the_whole_blob(azure):
    store, client = azure
    client.download_blob.return_value = downloader(b"img")
    assert store.get("screenshots/1/a") == b"img"
    client.download_blob.assert_called_once_with("screenshots/1/a")


def test_get_of_a_missing_blob_raises_not_found(azure):
    store, client = azure
    client.download_blob.side_effect = not_found()
    with pytest.raises(ArtifactNotFound):
        store.get("screenshots/1/missing")


def test_other_errors_are_not_hidden(azure):
    store, client = azure
    client.download_blob.side_effect = http_error(403, "AuthorizationPermissionMismatch")
    with pytest.raises(HttpResponseError):
        store.get("screenshots/1/a")


# open / ranges

def test_open_streams_in_read_chunks_and_reports_the_size(azure, monkeypatch):
    store, client = azure
    monkeypatch.setattr(artifact_store, "READ_CHUNK", 4)
    client.download_blob.return_value = downloader(b"0123456789")
    chunks, size = store.open("artifacts/1/a")
    assert size == 10
    assert list(chunks) == [b"012", b"3456", b"789"]  # no piece is larger than READ_CHUNK
    client.download_blob.assert_called_once_with("artifacts/1/a")


def test_open_of_a_missing_blob_raises_not_found_at_the_call(azure):
    store, client = azure
    client.download_blob.side_effect = not_found()
    with pytest.raises(ArtifactNotFound):
        store.open("artifacts/1/missing")


def test_get_range_asks_for_an_inclusive_range(azure):
    store, client = azure
    client.download_blob.return_value = downloader(b"2345")
    assert store.get_range("artifacts/1/a", 2, 5) == b"2345"
    client.download_blob.assert_called_once_with("artifacts/1/a", offset=2, length=4)


def test_open_range_streams_an_inclusive_range(azure):
    store, client = azure
    client.download_blob.return_value = downloader(b"2345")
    assert b"".join(store.open_range("artifacts/1/a", 2, 5)) == b"2345"
    client.download_blob.assert_called_once_with("artifacts/1/a", offset=2, length=4)


@pytest.mark.parametrize("method", ["get_range", "open_range"])
def test_a_range_past_the_end_raises_range_error(azure, method):
    store, client = azure
    client.download_blob.side_effect = http_error(416, "InvalidRange")
    with pytest.raises(ArtifactRangeError):
        getattr(store, method)("artifacts/1/a", 100, 200)


@pytest.mark.parametrize("method", ["get_range", "open_range"])
def test_a_range_of_a_missing_blob_raises_not_found(azure, method):
    store, client = azure
    client.download_blob.side_effect = not_found()
    with pytest.raises(ArtifactNotFound):
        getattr(store, method)("artifacts/1/missing", 0, 1)


@pytest.mark.parametrize("method", ["get_range", "open_range"])
def test_an_end_before_the_start_raises_range_error_and_a_missing_blob_still_not_found(azure, method):
    store, client = azure
    with pytest.raises(ArtifactRangeError):
        getattr(store, method)("artifacts/1/a", 5, 4)
    client.download_blob.assert_not_called()
    client.get_blob_client.return_value.get_blob_properties.side_effect = not_found()
    with pytest.raises(ArtifactNotFound):
        getattr(store, method)("artifacts/1/missing", 5, 4)


@pytest.mark.parametrize("method", ["get_range", "open_range"])
def test_a_range_of_an_empty_blob_raises_range_error(azure, method):
    """S3 answers 416 for bytes=0-0 of an empty object; the SDK returns no bytes instead."""
    store, client = azure
    client.download_blob.return_value = downloader(b"")
    with pytest.raises(ArtifactRangeError):
        getattr(store, method)("artifacts/1/empty", 0, 0)


# put_stream: staged blocks, committed once

def _staged(client):
    return [(c.args[0], c.args[1]) for c in client.get_blob_client.return_value.stage_block.call_args_list]


def _committed(client):
    blob = client.get_blob_client.return_value
    blob.commit_block_list.assert_called_once()
    call = blob.commit_block_list.call_args
    return [block.id for block in call.args[0]], call.kwargs["content_settings"].content_type


def test_put_stream_stages_part_size_blocks_and_keeps_a_short_last_block(azure, monkeypatch):
    store, client = azure
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"01", b"23456", b"789"]), "application/zip"))
    client.get_blob_client.assert_called_with("artifacts/1/a")
    staged = _staged(client)
    assert [data for _, data in staged] == [b"0123", b"4567", b"89"]
    ids, content_type = _committed(client)
    assert ids == [block_id for block_id, _ in staged] and content_type == "application/zip"
    assert len(set(ids)) == 3 and len({len(block_id) for block_id in ids}) == 1  # Azure wants one length per blob


def test_put_stream_block_ids_differ_between_uploads(azure):
    """Two uploads of the same content-addressed key at once must not overwrite each other's uncommitted blocks."""
    store, client = azure
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"x"]), "application/zip"))
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"x"]), "application/zip"))
    first, second = [c.args[0] for c in client.get_blob_client.return_value.stage_block.call_args_list]
    assert first != second


def test_put_stream_of_an_exact_multiple_has_no_empty_trailing_block(azure, monkeypatch):
    store, client = azure
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    asyncio.run(store.put_stream("artifacts/1/a", iter([b"01234567"]), "application/zip"))
    assert [data for _, data in _staged(client)] == [b"0123", b"4567"]
    assert len(_committed(client)[0]) == 2


def test_put_stream_of_an_empty_body_commits_an_empty_blob(azure):
    store, client = azure
    asyncio.run(store.put_stream("artifacts/1/a", iter([]), "application/zip"))
    assert _staged(client) == []
    assert _committed(client) == ([], "application/zip")


def test_put_stream_takes_an_async_iterator(azure):
    async def chunks():
        yield b"ab"
        yield b"cd"

    store, client = azure
    asyncio.run(store.put_stream("artifacts/1/a", chunks(), "application/zip"))
    assert [data for _, data in _staged(client)] == [b"abcd"]


def test_put_stream_reraises_and_commits_nothing_when_a_block_fails(azure, monkeypatch):
    store, client = azure
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)
    client.get_blob_client.return_value.stage_block.side_effect = http_error(500, "InternalError")
    with pytest.raises(HttpResponseError, match="InternalError"):
        asyncio.run(store.put_stream("artifacts/1/a", iter([b"01234567"]), "application/zip"))
    client.get_blob_client.return_value.commit_block_list.assert_not_called()


def test_put_stream_reraises_and_commits_nothing_when_the_iterator_fails(azure):
    async def chunks():
        yield b"01"
        raise ValueError("client went away")

    store, client = azure
    with pytest.raises(ValueError, match="client went away"):
        asyncio.run(store.put_stream("artifacts/1/a", chunks(), "application/zip"))
    client.get_blob_client.return_value.commit_block_list.assert_not_called()


# list_older / copy

def test_list_older_filters_by_last_modified(azure):
    store, client = azure
    cutoff = datetime(2026, 10, 20, tzinfo=timezone.utc)
    old, new = cutoff - timedelta(hours=1), cutoff + timedelta(hours=1)
    client.list_blobs.return_value = iter([
        SimpleNamespace(name="artifacts/1/incoming/a", last_modified=old),
        SimpleNamespace(name="artifacts/1/incoming/b", last_modified=new),
        SimpleNamespace(name="artifacts/1/incoming/c", last_modified=old)])
    assert store.list_older("artifacts/1/incoming/", cutoff) == ["artifacts/1/incoming/a", "artifacts/1/incoming/c"]
    client.list_blobs.assert_called_once_with(name_starts_with="artifacts/1/incoming/")


def _copy_target(made):
    source = made.clients[0].get_blob_client.return_value
    source.url = f"{ACCOUNT_URL}/{CONTAINER}/artifacts/1/incoming/x"
    return made.clients[1].get_blob_client.return_value


def test_copy_copies_server_side_with_the_copy_client(made):
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    target = _copy_target(made)
    target.start_copy_from_url.return_value = {"copy_status": "success", "copy_id": "c1"}
    store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    made.clients[0].get_blob_client.assert_called_with("artifacts/1/incoming/x")
    made.clients[1].get_blob_client.assert_called_with("artifacts/1/abc")
    target.start_copy_from_url.assert_called_once_with(f"{ACCOUNT_URL}/{CONTAINER}/artifacts/1/incoming/x")


def test_copy_of_a_missing_blob_raises_not_found(made):
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    _copy_target(made).start_copy_from_url.side_effect = not_found()
    with pytest.raises(ArtifactNotFound):
        store.copy("artifacts/1/missing", "artifacts/1/def")


def test_copy_waits_for_a_pending_copy(made, monkeypatch):
    monkeypatch.setattr("src.ingestion.utils.azure_blob_store.time.sleep", lambda _: None)
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    target = _copy_target(made)
    target.start_copy_from_url.return_value = {"copy_status": "pending", "copy_id": "c1"}
    target.get_blob_properties.side_effect = [SimpleNamespace(copy=SimpleNamespace(status=status))
                                              for status in ("pending", "success")]
    store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    assert target.get_blob_properties.call_count == 2


def test_copy_that_fails_raises(made):
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    _copy_target(made).start_copy_from_url.return_value = {"copy_status": "failed", "copy_id": "c1"}
    with pytest.raises(RuntimeError, match="failed"):
        store.copy("artifacts/1/incoming/x", "artifacts/1/abc")


def test_copy_still_pending_after_the_copy_timeout_is_aborted(made, monkeypatch):
    clock = iter(range(0, 1000, 30))
    monkeypatch.setattr("src.ingestion.utils.azure_blob_store.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("src.ingestion.utils.azure_blob_store.time.sleep", lambda _: None)
    store = AzureBlobArtifactStore(ACCOUNT_URL, CONTAINER)
    target = _copy_target(made)
    target.start_copy_from_url.return_value = {"copy_status": "pending", "copy_id": "c1"}
    target.get_blob_properties.return_value = SimpleNamespace(copy=SimpleNamespace(status="pending"))
    with pytest.raises(TimeoutError):
        store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    target.abort_copy.assert_called_once_with("c1")


# delete / delete_prefix: batches, partial failures

def _responses(*statuses, code="AuthorizationPermissionMismatch"):
    return iter([SimpleNamespace(status_code=status, headers={} if status < 300 else {"x-ms-error-code": code})
                 for status in statuses])


def test_delete_sends_batches_of_256_and_tolerates_missing_blobs(azure):
    store, client = azure
    keys = [f"screenshots/1/{i}" for i in range(600)]
    client.delete_blobs.side_effect = lambda *names, **_: _responses(*([202] * (len(names) - 1) + [404]))
    store.delete(keys)
    batches = [c.args for c in client.delete_blobs.call_args_list]
    assert [len(batch) for batch in batches] == [256, 256, 88]
    assert [key for batch in batches for key in batch] == keys
    for call in client.delete_blobs.call_args_list:
        assert call.kwargs["raise_on_any_failure"] is False
        assert call.kwargs["delete_snapshots"] == "include"


def test_delete_of_no_keys_sends_nothing(azure):
    store, client = azure
    store.delete([])
    client.delete_blobs.assert_not_called()


def test_delete_raises_when_some_blobs_were_not_deleted(azure):
    store, client = azure
    client.delete_blobs.return_value = _responses(202, 403)
    with pytest.raises(ArtifactDeleteError, match=r"1 of 2 objects not deleted, e.g. screenshots/1/b: Authorization"):
        store.delete(["screenshots/1/a", "screenshots/1/b"])


def test_delete_prefix_pages_and_counts(azure):
    store, client = azure
    first = [SimpleNamespace(name=f"screenshots/1/{i}") for i in range(3)]
    pages = MagicMock()
    pages.by_page.return_value = iter([iter(first), iter([SimpleNamespace(name="screenshots/1/x")])])
    client.list_blobs.return_value = pages
    client.delete_blobs.side_effect = lambda *names, **_: _responses(*[202] * len(names))
    assert store.delete_prefix("screenshots/1/") == 4
    client.list_blobs.assert_called_once_with(name_starts_with="screenshots/1/")
    assert [c.args for c in client.delete_blobs.call_args_list] == [
        ("screenshots/1/0", "screenshots/1/1", "screenshots/1/2"), ("screenshots/1/x",)]


def test_delete_prefix_raises_on_a_partial_batch(azure):
    store, client = azure
    pages = MagicMock()
    pages.by_page.return_value = iter([iter([SimpleNamespace(name="screenshots/1/a")])])
    client.list_blobs.return_value = pages
    client.delete_blobs.return_value = _responses(500, code="InternalError")
    with pytest.raises(ArtifactDeleteError, match="InternalError"):
        store.delete_prefix("screenshots/1/")


# The selector: ARTIFACTS_BACKEND

@pytest.fixture
def s3_settings(monkeypatch):
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_BUCKET", "qeos-artifacts")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_ACCESS_KEY", "key")
    monkeypatch.setattr(settings, "ARTIFACTS_S3_SECRET_KEY", "secret")


def test_the_backend_defaults_to_s3():
    assert type(settings).model_fields["ARTIFACTS_BACKEND"].default == "s3"
    assert type(settings).model_fields["ARTIFACTS_AZURE_ACCOUNT_URL"].default is None
    assert type(settings).model_fields["ARTIFACTS_AZURE_CONTAINER"].default == "qeos-artifacts"


def test_selector_picks_s3_by_default(monkeypatch, s3_settings):
    monkeypatch.setattr(settings, "ARTIFACTS_BACKEND", "s3")
    assert isinstance(get_artifact_store(), S3ArtifactStore)


def test_selector_picks_a_cached_azure_store(monkeypatch, made, s3_settings):
    monkeypatch.setattr(settings, "ARTIFACTS_BACKEND", "azure")
    monkeypatch.setattr(settings, "ARTIFACTS_AZURE_ACCOUNT_URL", ACCOUNT_URL)
    monkeypatch.setattr(settings, "ARTIFACTS_AZURE_CONTAINER", "other-container")
    store = get_artifact_store()
    assert isinstance(store, AzureBlobArtifactStore)
    assert get_artifact_store() is store
    assert made.clients[0].made_with["account_url"] == ACCOUNT_URL
    assert made.clients[0].made_with["container_name"] == "other-container"


@pytest.mark.parametrize("url", [None, ""])
def test_selector_without_an_account_url_has_no_store_and_warns_once(monkeypatch, made, caplog, url):
    monkeypatch.setattr(settings, "ARTIFACTS_BACKEND", "azure")
    monkeypatch.setattr(settings, "ARTIFACTS_AZURE_ACCOUNT_URL", url)
    with caplog.at_level(logging.WARNING, logger=artifact_store.__name__):
        assert get_artifact_store() is None
        assert get_artifact_store() is None
    warnings = [r for r in caplog.records if "ARTIFACTS_AZURE_ACCOUNT_URL" in r.getMessage()]
    assert len(warnings) == 1
    assert made.clients == []


def test_selector_with_an_unknown_backend_has_no_store_and_warns(monkeypatch, s3_settings, caplog):
    monkeypatch.setattr(settings, "ARTIFACTS_BACKEND", "gcs")
    with caplog.at_level(logging.WARNING, logger=artifact_store.__name__):
        assert get_artifact_store() is None
    assert any("gcs" in r.getMessage() for r in caplog.records)
