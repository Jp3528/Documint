"""Private S3-compatible storage. Callers must authorize access before reading objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from packages.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class ObjectStorage(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def check_ready(self) -> None: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"total_max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )

    def ensure_bucket(self) -> None:
        """Explicit bootstrap only. A permission error must not be mistaken for absence."""
        try:
            self.check_ready()
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def check_ready(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
