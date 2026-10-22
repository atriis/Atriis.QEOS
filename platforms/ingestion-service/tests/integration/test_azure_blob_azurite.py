"""AzureBlobArtifactStore (ADR-038) against Azurite, the Azure Storage emulator. Skipped unless AZURITE_URL is set:
    docker run -d --name <unique> -p 10000:10000 mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0
    AZURITE_URL=http://127.0.0.1:10000/devstoreaccount1 pytest tests/integration/test_azure_blob_azurite.py
Azurite takes its well-known development key here; the real store has no key and uses workload identity."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import ArtifactNotFound, ArtifactRangeError

URL = os.environ.get("AZURITE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="AZURITE_URL is not set")

# Azurite's published development account, not a secret
ACCOUNT = "devstoreaccount1"
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


@pytest.fixture
def store():
    from azure.core.credentials import AzureNamedKeyCredential
    from azure.storage.blob import ContainerClient

    from src.ingestion.utils.azure_blob_store import AzureBlobArtifactStore

    credential = AzureNamedKeyCredential(ACCOUNT, KEY)
    name = f"qeos-test-{uuid.uuid4().hex[:12]}"
    container = ContainerClient(account_url=URL, container_name=name, credential=credential)
    container.create_container()
    try:
        yield AzureBlobArtifactStore(URL, name, credential=credential)
    finally:
        container.delete_container()


def test_put_get_open_and_ranges(store):
    store.put("screenshots/1/a", b"0123456789", "image/png")
    assert store.get("screenshots/1/a") == b"0123456789"
    assert store._container.get_blob_client("screenshots/1/a").get_blob_properties().content_settings.content_type \
        == "image/png"
    chunks, size = store.open("screenshots/1/a")
    assert size == 10 and b"".join(chunks) == b"0123456789"
    assert store.get_range("screenshots/1/a", 2, 5) == b"2345"
    assert store.get_range("screenshots/1/a", 8, 99) == b"89"  # an end past the blob is cut, as S3 does
    assert b"".join(store.open_range("screenshots/1/a", 2, 5)) == b"2345"
    for start, end in ((10, 12), (11, 20), (5, 4)):
        with pytest.raises(ArtifactRangeError):
            store.get_range("screenshots/1/a", start, end)
        with pytest.raises(ArtifactRangeError):
            store.open_range("screenshots/1/a", start, end)


def test_missing_blobs_raise_not_found(store):
    for call in (lambda: store.get("artifacts/1/missing"), lambda: store.open("artifacts/1/missing"),
                 lambda: store.get_range("artifacts/1/missing", 0, 1),
                 lambda: store.open_range("artifacts/1/missing", 0, 1),
                 lambda: store.get_range("artifacts/1/missing", 5, 4),
                 lambda: store.copy("artifacts/1/missing", "artifacts/1/copy")):
        with pytest.raises(ArtifactNotFound):
            call()


def test_put_stream_in_blocks_copy_list_and_delete(store, monkeypatch):
    monkeypatch.setattr(artifact_store, "PART_SIZE", 4)

    async def chunks():
        for chunk in (b"PK", b"\x03\x04zip", b"-body"):
            yield chunk

    asyncio.run(store.put_stream("artifacts/1/incoming/x", chunks(), "application/zip"))
    blob = store._container.get_blob_client("artifacts/1/incoming/x")
    assert len(blob.get_block_list()[0]) == 3  # committed as staged blocks, not one put
    assert store.get("artifacts/1/incoming/x") == b"PK\x03\x04zip-body"
    asyncio.run(store.put_stream("artifacts/1/empty", iter([]), "application/zip"))
    assert store.get("artifacts/1/empty") == b""
    with pytest.raises(ArtifactRangeError):
        store.get_range("artifacts/1/empty", 0, 0)

    store.copy("artifacts/1/incoming/x", "artifacts/1/abc")
    assert store.get("artifacts/1/abc") == b"PK\x03\x04zip-body"
    copied = store._container.get_blob_client("artifacts/1/abc").get_blob_properties()
    assert copied.content_settings.content_type == "application/zip"

    now = datetime.now(timezone.utc)
    assert store.list_older("artifacts/1/incoming/", now + timedelta(minutes=5)) == ["artifacts/1/incoming/x"]
    assert store.list_older("artifacts/1/incoming/", now - timedelta(minutes=5)) == []

    store.delete(["artifacts/1/incoming/x", "artifacts/1/never-written"])  # a missing blob is not an error
    with pytest.raises(ArtifactNotFound):
        store.get("artifacts/1/incoming/x")


def test_put_stream_that_fails_leaves_no_blob(store):
    async def chunks():
        yield b"PK"
        raise ValueError("client went away")

    with pytest.raises(ValueError):
        asyncio.run(store.put_stream("artifacts/1/broken", chunks(), "application/zip"))
    with pytest.raises(ArtifactNotFound):
        store.get("artifacts/1/broken")


def test_delete_prefix_pages_and_keeps_other_projects(store, monkeypatch):
    for index in range(7):
        store.put(f"screenshots/1/{index}", b"x", "image/png")
    store.put("screenshots/10/a", b"x", "image/png")
    original = store._container.list_blobs
    monkeypatch.setattr(store._container, "list_blobs",
                        lambda **kwargs: original(results_per_page=3, **kwargs))  # three pages
    assert store.delete_prefix("screenshots/1/") == 7
    assert [blob.name for blob in original()] == ["screenshots/10/a"]


def test_a_missing_container_is_not_a_missing_artifact():
    from azure.core.credentials import AzureNamedKeyCredential

    from src.ingestion.utils.azure_blob_store import ArtifactContainerMissing, AzureBlobArtifactStore

    store = AzureBlobArtifactStore(URL, f"qeos-absent-{uuid.uuid4().hex[:12]}",
                                   credential=AzureNamedKeyCredential(ACCOUNT, KEY))
    for call in (lambda: store.get("screenshots/1/a"), lambda: store.open("screenshots/1/a"),
                 lambda: store.get_range("screenshots/1/a", 0, 1),
                 lambda: store.put("screenshots/1/a", b"x", "image/png"),
                 lambda: store.delete(["screenshots/1/a"]), lambda: store.delete_prefix("screenshots/1/")):
        with pytest.raises(ArtifactContainerMissing):
            call()
