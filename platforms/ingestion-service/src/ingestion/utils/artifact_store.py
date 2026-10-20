"""Artifact storage for screenshots (ADR-036): an S3-compatible bucket, MinIO in the compose files.
Only ingestion talks to it. Without all four ARTIFACTS_S3_* settings there is no store (None) and QEOS works as
before without screenshots. get_artifact_store() takes no request, so FastAPI routes and batch jobs (retention,
purge) call it the same way."""
import threading
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Protocol, Tuple

from src.ingestion.core.config import settings

DELETE_CHUNK = 1000  # S3 delete_objects takes at most 1,000 keys
# A slow store must not take every request thread: past this many calls at once, a request answers 503 at once
STORE_CALLS = 8
SLOT_WAIT_SECONDS = 2.0
BUSY_RETRY_AFTER = "5"


class ArtifactNotFound(Exception):
    """get() found no object under that key, in whichever store."""


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


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, media_type: str) -> None: ...

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
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",  # MinIO ignores it; boto3 wants one
            # MinIO is addressed by host and port, not by a bucket subdomain
            config=Config(
                s3={"addressing_style": "path"},
                # A MinIO that is down must fail an upload or a read in seconds, not hold its thread for minutes
                connect_timeout=5, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

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
