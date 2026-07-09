"""MinIO / S3-compatible storage via boto3."""

from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings
from app.storage.base import StorageNotFoundError

_storage: "S3Storage | None" = None


def get_storage() -> "S3Storage":
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage


class S3Storage:
    def __init__(self, client: Any | None = None, presign_client: Any | None = None) -> None:
        self._client = client
        self._presign_client = presign_client

    def _build_client(self, endpoint_url: str) -> Any:
        settings = get_settings()
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.storage_access_key or None,
            aws_secret_access_key=settings.storage_secret_key or None,
            region_name=settings.storage_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client(get_settings().storage_endpoint)
        return self._client

    @property
    def presign_client(self) -> Any:
        if self._presign_client is None:
            self._presign_client = self._build_client(get_settings().storage_public_endpoint)
        return self._presign_client

    @property
    def bucket(self) -> str:
        return get_settings().storage_bucket

    def put(self, key: str, body: bytes, *, content_type: str = "application/json") -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="no-cache, no-store, must-revalidate",
        )

    def verify_put(self, key: str, body: bytes, *, attempts: int = 5) -> None:
        """Read-after-write check so consumers never fetch a missing/stale object."""
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                got = self.get(key)
            except StorageNotFoundError as exc:
                last_err = exc
            else:
                if got == body:
                    return
                last_err = RuntimeError(f"byte mismatch for {key} ({len(got)} vs {len(body)})")
            if attempt < attempts:
                time.sleep(0.2 * attempt)
        raise RuntimeError(f"S3 object not readable after upload: {key}") from last_err

    def get(self, key: str) -> bytes:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise StorageNotFoundError(key) from exc
            raise
        return resp["Body"].read()

    def head(self, key: str) -> dict[str, Any]:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise StorageNotFoundError(key) from exc
            raise

    def presign_put(self, key: str) -> dict[str, Any]:
        settings = get_settings()
        url = self.presign_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": "application/json",
            },
            ExpiresIn=settings.presign_ttl_seconds,
        )
        return {
            "upload_url": url,
            "export_key": key,
            "expires_in": settings.presign_ttl_seconds,
        }

    def presign_get(self, key: str) -> dict[str, Any]:
        settings = get_settings()
        url = self.presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=settings.presign_ttl_seconds,
        )
        return {
            "download_url": url,
            "s3_result_key": key,
            "expires_in": settings.presign_ttl_seconds,
        }

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def _is_not_found(exc: ClientError) -> bool:
    code = exc.response.get("Error", {}).get("Code", "")
    return code in ("404", "NoSuchKey", "NotFound")
