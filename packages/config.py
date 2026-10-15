"""Shared configuration. Environment overrides .env; defaults are local demo values."""

from functools import lru_cache

from pydantic import SecretStr
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
