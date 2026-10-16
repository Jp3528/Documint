"""Shared configuration. Environment overrides .env; defaults are local demo values."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMIND_", env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://documind:documind-local-only@127.0.0.1:55432/documind"
    )
    redis_url: str = "redis://127.0.0.1:56379/0"
    result_backend: str = "redis://127.0.0.1:56379/1"
    s3_endpoint: str = "http://127.0.0.1:59000"
    s3_access_key: SecretStr = SecretStr("documind-local")
    s3_secret_key: SecretStr = SecretStr("documind-local-secret-only")
    s3_bucket: str = "documind-documents"
    s3_region: str = "us-east-1"
    auth_secret: SecretStr | None = None
    auth_issuer: str = "documind"
    auth_audience: str = "documind-api"
    access_ttl_seconds: int = Field(default=300, ge=60, le=900)
    refresh_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    cookie_secure: bool = False
    web_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    environment: Literal["development", "test", "demo", "production"] = "development"
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    docx_max_expanded_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=200 * 1024 * 1024)
    processing_pipeline_key: str = Field(default="text-v1", min_length=1, max_length=128)


@lru_cache
def get_settings() -> Settings:
    return Settings()
