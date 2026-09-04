from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from interview_api.workflow.errors import WorkflowNotFoundError, WorkflowProviderError


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class ObjectStorage(Protocol):
    async def ensure_bucket(self) -> None: ...

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def presign_download(
        self,
        key: str,
        *,
        filename: str,
        expires_seconds: int = 900,
    ) -> str: ...


class S3ObjectStorage:
    """Small async facade over a boto3 S3 client (AWS S3 or local MinIO)."""

    def __init__(self, client: Any, *, bucket: str, presign_client: Any | None = None) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self._client = client
        # With MinIO in Docker, IO uses ``http://minio:9000`` while browser
        # downloads need a client configured with e.g. ``http://localhost:9000``.
        # The host is covered by SigV4, so rewriting a completed URL is invalid.
        self._presign_client = presign_client or client
        self.bucket = bucket

    async def ensure_bucket(self) -> None:
        def ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except Exception:
                # MinIO/local demo should be able to bootstrap itself.  AWS users can
                # pre-create the bucket and deny CreateBucket after initialization.
                self._client.create_bucket(Bucket=self.bucket)

        try:
            await asyncio.to_thread(ensure)
        except Exception as exc:
            raise WorkflowProviderError(
                "Object storage bucket is unavailable.",
                details={"bucket": self.bucket},
            ) from exc

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        self._validate_key(key)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=dict(metadata or {}),
            )
        except Exception as exc:
            raise WorkflowProviderError(
                "Could not persist an interview object.", details={"objectKey": key}
            ) from exc
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    async def get_bytes(self, key: str) -> bytes:
        self._validate_key(key)

        def read() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()

        try:
            return await asyncio.to_thread(read)
        except Exception as exc:
            raise WorkflowNotFoundError(
                "The stored interview object was not found.",
                details={"objectKey": key},
            ) from exc

    async def presign_download(
        self,
        key: str,
        *,
        filename: str,
        expires_seconds: int = 900,
    ) -> str:
        self._validate_key(key)
        try:
            return await asyncio.to_thread(
                self._presign_client.generate_presigned_url,
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": self._content_disposition(filename),
                },
                ExpiresIn=expires_seconds,
            )
        except Exception as exc:
            raise WorkflowProviderError(
                "Could not create a media download URL.", details={"objectKey": key}
            ) from exc

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("Unsafe object key")

    @staticmethod
    def _content_disposition(filename: str) -> str:
        safe = "".join(
            character for character in filename if character.isalnum() or character in ".-_ "
        )
        return f'attachment; filename="{(safe or "download").strip()}"'


class MemoryObjectStorage:
    """Deterministic object store for tests; never selected by production wiring."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}

    async def ensure_bucket(self) -> None:
        return None

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        S3ObjectStorage._validate_key(key)
        self.objects[key] = (bytes(data), content_type, dict(metadata or {}))
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    async def get_bytes(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise WorkflowNotFoundError(details={"objectKey": key}) from exc

    async def presign_download(
        self,
        key: str,
        *,
        filename: str,
        expires_seconds: int = 900,
    ) -> str:
        del expires_seconds
        if key not in self.objects:
            raise WorkflowNotFoundError(details={"objectKey": key})
        return f"memory://workflow/{key}?filename={filename}"
