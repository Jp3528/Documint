import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pydantic import BaseModel, ValidationError

from packages.config import Settings

password_hasher = PasswordHash.recommended()
_DUMMY_HASH = password_hasher.hash("dummy-verification-only")


class AuthenticationError(Exception):
    """Deliberately generic: callers must not disclose identity or session existence."""


class AuthConfigurationError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("password must contain between 12 and 128 characters")
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str | None) -> tuple[bool, str | None]:
    try:
        valid, updated = password_hasher.verify_and_update(password, encoded or _DUMMY_HASH)
        return valid and encoded is not None, updated
    except (PwdlibError, ValueError):
        return False, None


def refresh_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_refresh() -> str:
    return secrets.token_urlsafe(32)


class AccessClaims(BaseModel):
    sub: UUID
    sid: UUID
    jti: UUID
    type: Literal["access"]
    exp: int
    iat: int
    iss: str
    aud: str


class TokenCodec:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = settings.auth_secret.get_secret_value() if settings.auth_secret else ""
        if len(self.key.encode()) < 32:
            raise AuthConfigurationError("auth signing key is not configured")

    def issue(self, user_id: UUID, session_id: UUID) -> str:
        now = int(utcnow().timestamp())
        claims = AccessClaims(
            sub=user_id,
            sid=session_id,
            jti=uuid4(),
            type="access",
            iat=now,
            exp=now + self.settings.access_ttl_seconds,
            iss=self.settings.auth_issuer,
            aud=self.settings.auth_audience,
        )
        return jwt.encode(claims.model_dump(mode="json"), self.key, algorithm="HS256")

    def decode(self, token: str) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self.key,
                algorithms=["HS256"],
                issuer=self.settings.auth_issuer,
                audience=self.settings.auth_audience,
                options={"require": ["sub", "sid", "jti", "type", "exp", "iat", "iss", "aud"]},
            )
            return AccessClaims.model_validate(payload)
        except (jwt.InvalidTokenError, ValidationError, ValueError) as exc:
            raise AuthenticationError from exc
