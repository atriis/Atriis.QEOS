"""Azure Blob Storage behind the ArtifactStore interface (ADR-038), for QEOS on AKS: ARTIFACTS_BACKEND=azure. The same
keys and errors as S3ArtifactStore. It authenticates with DefaultAzureCredential, which is workload identity in the
pod: no account key or SAS exists anywhere in QEOS, and the container stays private."""
import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Iterator, List, Optional, Tuple

from src.ingestion.utils import artifact_store as base
from src.ingestion.utils.artifact_store import (
    ArtifactDeleteError, ArtifactNotFound, ArtifactRangeError, Chunks, _each)

logger = logging.getLogger(__name__)

# A blob batch takes at most 256 sub-requests
DELETE_CHUNK = 256
# The SDK downloads in pieces of this size: a streamed read holds one piece, never a whole 100 MB trace
STREAM_CHUNK = 4 * 1024 * 1024
COPY_POLL_SECONDS = 1.0


def _status(exc: Exception) -> Optional[int]:
    return getattr(exc, "status_code", None)


def _missing(exc: Exception) -> bool:
    from azure.core.exceptions import ResourceNotFoundError

    return isinstance(exc, ResourceNotFoundError) or _status(exc) == 404


def _bad_range(exc: Exception) -> bool:
    return _status(exc) == 416 or getattr(exc, "error_code", None) == "InvalidRange"


def _pieces(chunks: Iterator[bytes]) -> Iterator[bytes]:
    """The SDK's STREAM_CHUNK pieces cut to READ_CHUNK, as S3ArtifactStore streams."""
    size = base.READ_CHUNK
    for chunk in chunks:
        for at in range(0, len(chunk), size):
            yield chunk[at:at + size]


class AzureBlobArtifactStore:
    def __init__(self, account_url: str, container: str, credential: Any = None) -> None:
        """credential defaults to DefaultAzureCredential(); the Azurite test passes the emulator's well-known key."""
        from azure.storage.blob import ContainerClient, ExponentialRetry

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        # The SDK logs every request's headers at INFO
        logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

        def client(read_timeout: int):
            return ContainerClient(
                account_url=account_url, container_name=container, credential=credential,
                # As the S3 store: an unreachable store fails an upload or a read in seconds, with one retry (the
                # SDK's default is 3 retries starting 15 s apart)
                connection_timeout=5, read_timeout=read_timeout,
                retry_policy=ExponentialRetry(initial_backoff=1, increment_base=2, retry_total=1,
                                              random_jitter_range=1),
                max_single_get_size=STREAM_CHUNK, max_chunk_get_size=STREAM_CHUNK,
            )

        self._container = client(10)
        self._copy_container = client(base.COPY_READ_TIMEOUT)

    def put(self, key: str, data: bytes, media_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self._container.upload_blob(name=key, data=data, overwrite=True,
                                    content_settings=ContentSettings(content_type=media_type))

    def get(self, key: str) -> bytes:
        try:
            return self._container.download_blob(key).readall()
        except Exception as exc:
            if _missing(exc):
                raise ArtifactNotFound(key) from exc
            raise

    async def put_stream(self, key: str, chunks: Chunks, media_type: str) -> None:
        """Block blob: each PART_SIZE piece is staged as a block in a worker thread, and one commit makes the blob.
        Until that commit nothing is visible under the key, so a failure, a cancelled request included, leaves no
        object (or the previous one); Azure discards uncommitted blocks after a week. Block ids carry a per-upload
        prefix: two uploads of the same content-addressed key at once never overwrite each other's blocks."""
        from azure.storage.blob import BlobBlock, ContentSettings

        blob = self._container.get_blob_client(key)
        upload = uuid.uuid4().hex
        blocks: List[BlobBlock] = []
        buffer = bytearray()

        async def send(data: bytes) -> None:
            block_id = f"{upload}-{len(blocks):06d}"  # one length for every id of a blob, as Azure requires
            await asyncio.to_thread(blob.stage_block, block_id, data)
            blocks.append(BlobBlock(block_id=block_id))

        async for chunk in _each(chunks):
            buffer.extend(chunk)
            while len(buffer) >= base.PART_SIZE:
                await send(bytes(buffer[:base.PART_SIZE]))
                del buffer[:base.PART_SIZE]
        if buffer:  # the last block may be small; an empty body commits an empty list, an empty blob
            await send(bytes(buffer))
        await asyncio.to_thread(blob.commit_block_list, blocks,
                                content_settings=ContentSettings(content_type=media_type))

    def open(self, key: str) -> Tuple[Iterator[bytes], int]:
        try:
            download = self._container.download_blob(key)
        except Exception as exc:
            if _missing(exc):
                raise ArtifactNotFound(key) from exc
            raise
        return _pieces(download.chunks()), int(download.size)

    def _ranged(self, key: str, start: int, end: int):
        """The downloader for start..end, inclusive. Errors are raised here, before the first byte."""
        try:
            if end < start:  # S3 would ignore such a Range; the interface says it is an error, after a missing key
                self._container.get_blob_client(key).get_blob_properties()
                raise ArtifactRangeError(f"{key} bytes={start}-{end}")
            download = self._container.download_blob(key, offset=start, length=end - start + 1)
        except ArtifactRangeError:
            raise
        except Exception as exc:
            if _missing(exc):
                raise ArtifactNotFound(key) from exc
            if _bad_range(exc):
                raise ArtifactRangeError(f"{key} bytes={start}-{end}") from exc
            raise
        if not download.size:  # an empty blob: S3 answers 416 for any range of it, the SDK no bytes
            raise ArtifactRangeError(f"{key} bytes={start}-{end}")
        return download

    def get_range(self, key: str, start: int, end: int) -> bytes:
        return self._ranged(key, start, end).readall()

    def open_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        return _pieces(self._ranged(key, start, end).chunks())

    def list_older(self, prefix: str, older_than: datetime) -> List[str]:
        return [blob.name for blob in self._container.list_blobs(name_starts_with=prefix)
                if blob.last_modified < older_than]

    def copy(self, src_key: str, dst_key: str) -> None:
        """A server-side copy inside the account, authorised by the same identity. Within one account it is usually
        done when the call answers; one still pending is polled for COPY_READ_TIMEOUT, then aborted."""
        source = self._container.get_blob_client(src_key).url
        target = self._copy_container.get_blob_client(dst_key)
        try:
            started = target.start_copy_from_url(source)
        except Exception as exc:
            if _missing(exc):
                raise ArtifactNotFound(src_key) from exc
            raise
        status, copy_id = started.get("copy_status"), started.get("copy_id")
        deadline = time.monotonic() + base.COPY_READ_TIMEOUT
        while status == "pending":
            if time.monotonic() >= deadline:
                target.abort_copy(copy_id)
                raise TimeoutError(f"copy of {src_key} to {dst_key} still pending after {base.COPY_READ_TIMEOUT} s")
            time.sleep(COPY_POLL_SECONDS)
            status = target.get_blob_properties().copy.status
        if status != "success":
            raise RuntimeError(f"copy of {src_key} to {dst_key} {status}")

    def delete(self, keys: List[str]) -> None:
        for start in range(0, len(keys), DELETE_CHUNK):
            chunk = keys[start:start + DELETE_CHUNK]
            responses = self._container.delete_blobs(*chunk, delete_snapshots="include", raise_on_any_failure=False)
            # A blob already gone is deleted, as with S3; any other failure leaves it there, and a purge must not
            # record success while objects remain
            errors = [(key, response) for key, response in zip(chunk, responses)
                      if response.status_code >= 300 and response.status_code != 404]
            if errors:
                key, response = errors[0]
                code = response.headers.get("x-ms-error-code") or response.status_code
                raise ArtifactDeleteError(f"{len(errors)} of {len(chunk)} objects not deleted, e.g. {key}: {code}")

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        for page in self._container.list_blobs(name_starts_with=prefix).by_page():
            keys = [blob.name for blob in page]
            self.delete(keys)
            deleted += len(keys)
        return deleted
