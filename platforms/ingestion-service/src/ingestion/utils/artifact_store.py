"""Artifact storage for screenshots (ADR-036): an S3-compatible bucket, MinIO in the compose files.
Only ingestion talks to it. Without all four ARTIFACTS_S3_* settings there is no store (None) and QEOS works as
before without screenshots. get_artifact_store() takes no request, so FastAPI routes and batch jobs (retention,
purge) call it the same way."""
import asyncio
import logging
import threading
from contextlib import contextmanager
from typing import AsyncIterator, Dict, Iterator, List, Optional, Protocol, Tuple, Union

from src.ingestion.core.config import settings

logger = logging.getLogger(__name__)

DELETE_CHUNK = 1000  # S3 delete_objects takes at most 1,000 keys
PART_SIZE = 8 * 1024 * 1024  # multipart parts of a streamed upload (S3 wants at least 5 MB, except the last)
READ_CHUNK = 64 * 1024
# A slow store must not take every request thread: past this many calls at once, a request answers 503 at once
STORE_CALLS = 8
SLOT_WAIT_SECONDS = 2.0
BUSY_RETRY_AFTER = "5"
# A server-side copy answers only when it is done: a 100 MB trace needs more than the 10 s read timeout
COPY_READ_TIMEOUT = 60


class ArtifactNotFound(Exception):
    """get() found no object under that key, in whichever store."""


class ArtifactRangeError(Exception):
    """get_range() asked for bytes outside the object (S3 InvalidRange, HTTP 416)."""


class ArtifactDeleteError(Exception):
    """The store refused to delete some objects: they are still there."""


class ArtifactStoreBusy(Exception):
    """Every request slot for the store is taken: the caller answers 503 with Retry-After."""


_slots = threading.BoundedSemaphore(STORE_CALLS)


@contextmanager
def store_slot() -> Iterator[None]:
    """Holds one of STORE_CALLS slots around a request's store call, or raises ArtifactStoreBusy after a short wait.
    Hold no database connection while in it: a hung store then costs threads, never the pool that run uploads use."""
    if not _slots.acquire(timeout=SLOT_WAIT_SECONDS):
        raise ArtifactStoreBusy()
    try:
        yield
    finally:
        _slots.release()


def screenshot_key(project_id: int, sha256: str) -> str:
    """Content-addressed per project: the same image uploaded twice is stored once."""
    return f"screenshots/{project_id}/{sha256}"


def artifact_key(project_id: int, sha256: str) -> str:
    """Traces (ADR-037), content-addressed per project like screenshots."""
    return f"artifacts/{project_id}/{sha256}"


Chunks = Union[AsyncIterator[bytes], Iterator[bytes]]


async def _each(chunks: Chunks) -> AsyncIterator[bytes]:
    if hasattr(chunks, "__aiter__"):
        async for chunk in chunks:  # type: ignore[union-attr]
            yield chunk
    else:
        for chunk in chunks:  # type: ignore[union-attr]
            yield chunk


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, media_type: str) -> None: ...

    async def put_stream(self, key: str, chunks: Chunks, media_type: str) -> None:
        """Stores the chunks as one object without holding them all in memory. A failure leaves no object."""
        ...

    def open(self, key: str) -> Tuple[Iterator[bytes], int]:
        """A streaming read and the object's size. Raises ArtifactNotFound."""
        ...

    def get_range(self, key: str, start: int, end: int) -> bytes:
        """Bytes start..end, both inclusive (an HTTP Range); an end past the object is cut to it. Raises
        ArtifactNotFound, and ArtifactRangeError when start is at or past the end or end is before start."""
        ...

    def copy(self, src_key: str, dst_key: str) -> None:
        """Copies one object to another key, inside the store. Raises ArtifactNotFound."""
        ...

    def get(self, key: str) -> bytes: ...

    def delete(self, keys: List[str]) -> None: ...

    def delete_prefix(self, prefix: str) -> int:
        """Deletes every object whose key starts with prefix and returns how many. End a project's prefix with
        "/": "screenshots/1" would also match "screenshots/10/"."""
        ...


class MemoryArtifactStore:
    """For tests."""

    def __init__(self) -> None:
        self.objects: Dict[str, Tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, media_type: str) -> None:
        self.objects[key] = (data, media_type)

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise ArtifactNotFound(key) from None

    async def put_stream(self, key: str, chunks: Chunks, media_type: str) -> None:
        parts = [chunk async for chunk in _each(chunks)]
        self.objects[key] = (b"".join(parts), media_type)

    def open(self, key: str) -> Tuple[Iterator[bytes], int]:
        data = self.get(key)
        return iter([data[start:start + READ_CHUNK] for start in range(0, len(data), READ_CHUNK)]), len(data)

    def get_range(self, key: str, start: int, end: int) -> bytes:
        data = self.get(key)
        if start >= len(data) or end < start:
            raise ArtifactRangeError(f"{key} bytes={start}-{end}")
        return data[start:end + 1]

    def copy(self, src_key: str, dst_key: str) -> None:
        try:
            self.objects[dst_key] = self.objects[src_key]
        except KeyError:
            raise ArtifactNotFound(src_key) from None

    def delete(self, keys: List[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)

    def delete_prefix(self, prefix: str) -> int:
        doomed = [key for key in self.objects if key.startswith(prefix)]
        self.delete(doomed)
        return len(doomed)


class S3ArtifactStore:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = bucket

        def client(read_timeout: int):
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="us-east-1",  # MinIO ignores it; boto3 wants one
                # MinIO is addressed by host and port, not by a bucket subdomain
                config=Config(
                    s3={"addressing_style": "path"},
                    # A MinIO that is down must fail an upload or a read in seconds, not hold its thread for minutes
                    connect_timeout=5, read_timeout=read_timeout, retries={"max_attempts": 2, "mode": "standard"},
                ),
            )

        self._client = client(10)
        self._copy_client = client(COPY_READ_TIMEOUT)

    def put(self, key: str, data: bytes, media_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=media_type)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise ArtifactNotFound(key) from exc
            raise

    async def put_stream(self, key: str, chunks: Chunks, media_type: str) -> None:
        """Multipart upload in PART_SIZE parts; boto3 runs in a worker thread so the event loop stays free. Any
        failure, a cancelled request included, aborts the upload and re-raises the original error. A part still in
        flight when a request is cancelled can land after the abort: a bucket lifecycle rule for incomplete
        multipart uploads is the safety net. A sync iterator is consumed on the event loop, fine for in-memory data;
        the caller wraps disk reads (asyncio.to_thread) so they do not block it."""
        upload_id = (await asyncio.to_thread(
            self._client.create_multipart_upload, Bucket=self._bucket, Key=key, ContentType=media_type))["UploadId"]
        parts: List[dict] = []
        buffer = bytearray()

        async def send(data: bytes) -> None:
            number = len(parts) + 1
            response = await asyncio.to_thread(
                self._client.upload_part, Bucket=self._bucket, Key=key, UploadId=upload_id, PartNumber=number,
                Body=data)
            parts.append({"ETag": response["ETag"], "PartNumber": number})

        try:
            async for chunk in _each(chunks):
                buffer.extend(chunk)
                while len(buffer) >= PART_SIZE:
                    await send(bytes(buffer[:PART_SIZE]))
                    del buffer[:PART_SIZE]
            if buffer or not parts:  # the last part may be small; an empty object still needs one part
                await send(bytes(buffer))
            await asyncio.to_thread(
                self._client.complete_multipart_upload, Bucket=self._bucket, Key=key, UploadId=upload_id,
                MultipartUpload={"Parts": parts})
        except BaseException:
            try:  # a failing abort must not hide the error that caused it
                await asyncio.shield(asyncio.to_thread(
                    self._client.abort_multipart_upload, Bucket=self._bucket, Key=key, UploadId=upload_id))
            except Exception:
                logger.warning("could not abort multipart upload %s of %s", upload_id, key, exc_info=True)
            raise

    def open(self, key: str) -> Tuple[Iterator[bytes], int]:
        from botocore.exceptions import ClientError

        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise ArtifactNotFound(key) from exc
            raise
        return body["Body"].iter_chunks(READ_CHUNK), int(body["ContentLength"])

    def get_range(self, key: str, start: int, end: int) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}")["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise ArtifactNotFound(key) from exc
            if code == "InvalidRange" or exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 416:
                raise ArtifactRangeError(f"{key} bytes={start}-{end}") from exc
            raise

    def copy(self, src_key: str, dst_key: str) -> None:
        """One copy_object call: enough for a trace (at most 100 MB); S3 wants a multipart copy only past 5 GB. Its
        own client, with COPY_READ_TIMEOUT."""
        from botocore.exceptions import ClientError

        try:
            self._copy_client.copy_object(Bucket=self._bucket, Key=dst_key,
                                          CopySource={"Bucket": self._bucket, "Key": src_key})
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise ArtifactNotFound(src_key) from exc
            raise

    def delete(self, keys: List[str]) -> None:
        for start in range(0, len(keys), DELETE_CHUNK):
            chunk = keys[start:start + DELETE_CHUNK]
            response = self._client.delete_objects(
                Bucket=self._bucket, Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True})
            # A 200 can still carry per-key failures; a purge must not record success while objects remain
            errors = response.get("Errors") or []
            if errors:
                first = errors[0]
                raise ArtifactDeleteError(
                    f"{len(errors)} of {len(chunk)} objects not deleted, e.g. {first.get('Key')}: {first.get('Code')}")

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        pages = self._client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix)
        for page in pages:
            keys = [item["Key"] for item in page.get("Contents", [])]
            self.delete(keys)
            deleted += len(keys)
        return deleted


_lock = threading.Lock()
_store: Optional[ArtifactStore] = None


def reset() -> None:
    """Forgets the cached store (tests, after changing the settings)."""
    global _store
    with _lock:
        _store = None


def get_artifact_store() -> Optional[ArtifactStore]:
    """The configured store, built once, or None when any ARTIFACTS_S3_* setting is unset or empty."""
    global _store
    endpoint, bucket = settings.ARTIFACTS_S3_ENDPOINT, settings.ARTIFACTS_S3_BUCKET
    access_key, secret_key = settings.ARTIFACTS_S3_ACCESS_KEY, settings.ARTIFACTS_S3_SECRET_KEY
    if not (endpoint and bucket and access_key and secret_key):
        return None
    with _lock:
        if _store is None:
            _store = S3ArtifactStore(endpoint, bucket, access_key, secret_key)
        return _store
