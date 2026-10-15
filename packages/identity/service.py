"""Session transactions live here; HTTP routers never implement token rotation policy."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.config import Settings

from .models import AuthSession, RefreshToken, User
from .security import (
    AuthenticationError,
    TokenCodec,
    new_refresh,
    refresh_digest,
    utcnow,
    verify_password,
)


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int


class AuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _issue(self, user: User, family: AuthSession, codec: TokenCodec) -> IssuedSession:
        raw = new_refresh()
        self.db.add(RefreshToken(digest=refresh_digest(raw), session_id=family.id))
        return IssuedSession(
            codec.issue(user.id, family.id),
            raw,
            self.settings.access_ttl_seconds,
            max(0, int((family.expires_at - utcnow()).total_seconds())),
        )

    def login(self, email: str, password: str) -> IssuedSession:
        codec = TokenCodec(self.settings)
        user = self.db.scalar(select(User).where(User.email == email.strip().casefold()))
        valid, updated = verify_password(password, user.password_hash if user else None)
        if not valid or user is None or user.status != "ACTIVE":
            raise AuthenticationError
        if updated:
            user.password_hash = updated
        user.last_login_at = utcnow()
        family = AuthSession(
            user_id=user.id,
            expires_at=utcnow() + timedelta(seconds=self.settings.refresh_ttl_seconds),
        )
        self.db.add(family)
        self.db.flush()
        issued = self._issue(user, family, codec)
        self.db.commit()
        return issued

    def refresh(self, raw: str) -> IssuedSession:
        codec = TokenCodec(self.settings)
        token = self.db.scalar(
            select(RefreshToken).where(RefreshToken.digest == refresh_digest(raw)).with_for_update()
        )
        if token is None:
            raise AuthenticationError
        family = self.db.scalar(
            select(AuthSession).where(AuthSession.id == token.session_id).with_for_update()
        )
        if family is None:
            raise AuthenticationError
        user = self.db.get(User, family.user_id)
        if (
            token.consumed_at is not None
            or family.revoked_at is not None
            or family.expires_at <= utcnow()
            or user is None
            or user.status != "ACTIVE"
        ):
            family.revoked_at = family.revoked_at or utcnow()
            self.db.commit()  # Persist replay revocation even though the response is 401.
            raise AuthenticationError
        token.consumed_at = utcnow()
        issued = self._issue(user, family, codec)
        self.db.commit()
        return issued

    def logout(self, raw: str | None) -> None:
        if raw is None:
            return
        token = self.db.get(RefreshToken, refresh_digest(raw))
        if token:
            family = self.db.scalar(
                select(AuthSession).where(AuthSession.id == token.session_id).with_for_update()
            )
            if family:
                family.revoked_at = family.revoked_at or utcnow()
                self.db.commit()

    def authenticate(self, access_token: str) -> User:
        claims = TokenCodec(self.settings).decode(access_token)
        family = self.db.get(AuthSession, claims.sid)
        user = self.db.get(User, claims.sub)
        if (
            family is None
            or user is None
            or family.user_id != user.id
            or family.revoked_at is not None
            or family.expires_at <= utcnow()
            or user.status != "ACTIVE"
        ):
            raise AuthenticationError
        return user
