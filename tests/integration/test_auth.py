"""Session and API rules against real PostgreSQL with rollback-isolated test data."""

import os
import secrets
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.auth import COOKIE_NAME
from apps.api.dependencies import get_session
from apps.api.main import create_app
from packages.config import Settings
from packages.database import make_engine
from packages.identity.models import AuthSession, RefreshToken, User
from packages.identity.security import AuthenticationError, hash_password, refresh_digest, utcnow
from packages.identity.service import AuthService
from scripts.seed_demo import PUBLIC_DEMO_PASSWORD, demo_personas, seed_identities

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(
        os.getenv("DOCUMIND_TEST_INFRA") != "1",
        reason="requires the migrated PostgreSQL from Compose",
    ),
]
CSRF = {"X-DocuMind-CSRF": "1"}


@dataclass
class AuthHarness:
    client: TestClient
    db: Session
    password: str
    user_id: UUID
    email: str

    def login(self) -> str:
        response = self.client.post(
            "/auth/login", headers=CSRF, json={"email": self.email, "password": self.password}
        )
        assert response.status_code == 200
        return str(response.json()["access_token"])


@pytest.fixture
def auth(isolated_db: sessionmaker[Session]) -> Iterator[AuthHarness]:
    settings = Settings(auth_secret=SecretStr(secrets.token_urlsafe(48)))
    factory = isolated_db
    password = secrets.token_urlsafe(24)
    db = factory()
    email = f"test-{uuid4().hex}@documind.example"
    user = User(
        email=email, display_name="Persona sintética", password_hash=hash_password(password)
    )
    db.add(user)
    db.commit()

    def override_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield AuthHarness(client, db, password, user.id, email)
    finally:
        db.close()


def test_login_profile_cookie_hash_and_normalized_email(auth: AuthHarness) -> None:
    response = auth.client.post(
        "/auth/login",
        headers=CSRF,
        json={"email": " " + auth.email.upper() + " ", "password": auth.password},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/auth" in cookie
    raw = auth.client.cookies.get(COOKIE_NAME)
    stored = auth.db.scalar(select(RefreshToken))
    assert raw and stored and stored.digest == refresh_digest(raw) and stored.digest != raw
    profile = auth.client.get(
        "/me", headers={"Authorization": "Bearer " + response.json()["access_token"]}
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == auth.email
    assert "password" not in profile.text


def test_refresh_rotates_and_replay_revokes_the_entire_family(auth: AuthHarness) -> None:
    original_access = auth.login()
    original_refresh = auth.client.cookies.get(COOKIE_NAME)
    response = auth.client.post("/auth/refresh", headers=CSRF)
    assert response.status_code == 200
    replacement_access = response.json()["access_token"]
    replacement_refresh = auth.client.cookies.get(COOKIE_NAME)
    assert replacement_refresh != original_refresh
    assert replacement_access != original_access
    replay = auth.client.post(
        "/auth/refresh", headers={**CSRF, "Cookie": f"{COOKIE_NAME}={original_refresh}"}
    )
    assert replay.status_code == 401
    assert "max-age=0" in replay.headers["set-cookie"].lower()
    assert (
        auth.client.get(
            "/me", headers={"Authorization": "Bearer " + replacement_access}
        ).status_code
        == 401
    )
    assert (
        auth.client.post(
            "/auth/refresh", headers={**CSRF, "Cookie": f"{COOKIE_NAME}={replacement_refresh}"}
        ).status_code
        == 401
    )
    auth.db.expire_all()
    assert auth.db.scalar(select(AuthSession.revoked_at)) is not None


def test_logout_revokes_immediately_and_is_idempotent(auth: AuthHarness) -> None:
    token = auth.login()
    response = auth.client.post("/auth/logout", headers=CSRF)
    assert response.status_code == 204 and response.content == b""
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert auth.client.get("/me", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert auth.client.post("/auth/logout", headers=CSRF).status_code == 204


def test_wrong_unknown_and_inactive_logins_have_the_same_response(auth: AuthHarness) -> None:
    responses = []
    for email, password in ((auth.email, "incorrect"), ("missing@documind.example", auth.password)):
        responses.append(
            auth.client.post(
                "/auth/login", headers=CSRF, json={"email": email, "password": password}
            )
        )
    user = auth.db.get(User, auth.user_id)
    assert user
    user.status = "INACTIVE"
    auth.db.commit()
    responses.append(
        auth.client.post(
            "/auth/login", headers=CSRF, json={"email": auth.email, "password": auth.password}
        )
    )
    assert all(response.status_code == 401 for response in responses)
    assert len({response.text for response in responses}) == 1


def test_deactivation_blocks_existing_access_and_refresh(auth: AuthHarness) -> None:
    access = auth.login()
    user = auth.db.get(User, auth.user_id)
    assert user
    user.status = "INACTIVE"
    auth.db.commit()
    assert auth.client.get("/me", headers={"Authorization": "Bearer " + access}).status_code == 401
    assert auth.client.post("/auth/refresh", headers=CSRF).status_code == 401


def test_session_expiration_blocks_access_and_rotation(auth: AuthHarness) -> None:
    access = auth.login()
    family = auth.db.scalar(select(AuthSession))
    assert family
    family.expires_at = utcnow() - timedelta(seconds=1)
    auth.db.commit()
    assert auth.client.get("/me", headers={"Authorization": "Bearer " + access}).status_code == 401
    assert auth.client.post("/auth/refresh", headers=CSRF).status_code == 401


def test_refresh_missing_or_unknown_is_generic(auth: AuthHarness) -> None:
    assert auth.client.post("/auth/refresh", headers=CSRF).status_code == 401
    response = auth.client.post(
        "/auth/refresh", headers={**CSRF, "Cookie": f"{COOKIE_NAME}=unknown"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión no válida"}


def test_logout_does_not_revoke_another_session(auth: AuthHarness) -> None:
    first = auth.login()
    second = auth.login()
    assert auth.client.post("/auth/logout", headers=CSRF).status_code == 204
    assert auth.client.get("/me", headers={"Authorization": "Bearer " + second}).status_code == 401
    assert auth.client.get("/me", headers={"Authorization": "Bearer " + first}).status_code == 200


def test_explicit_demo_seed_is_idempotent_and_blocks_production(auth: AuthHarness) -> None:
    settings = Settings(environment="test")
    people = demo_personas()
    prefix = uuid4().hex
    for person in people.personas:
        person.id = prefix + "-" + person.id
        person.email = prefix + "." + person.email
    assert seed_identities(auth.db, settings, people) == 10
    assert seed_identities(auth.db, settings, people) == 0
    inactive_email = next(person.email for person in people.personas if not person.active)
    inactive = auth.db.scalar(select(User).where(User.email == inactive_email))
    assert inactive and inactive.status == "INACTIVE"
    assert PUBLIC_DEMO_PASSWORD not in inactive.password_hash
    with pytest.raises(ValueError, match="production"):
        seed_identities(auth.db, Settings(environment="production"), people)


def test_simultaneous_refresh_has_one_winner_and_replay_revokes_it() -> None:
    """Separate real connections test row locks, not a mock or a shared test transaction."""
    settings = Settings(auth_secret=SecretStr(secrets.token_urlsafe(48)))
    engine = make_engine(settings)
    factory = sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    password = secrets.token_urlsafe(24)
    email = f"concurrency-{user_id.hex}@documind.example"
    try:
        with factory() as db:
            db.add(
                User(
                    id=user_id,
                    email=email,
                    display_name="Concurrent test",
                    password_hash=hash_password(password),
                )
            )
            db.commit()
            issued = AuthService(db, settings).login(email, password)
        barrier = Barrier(2)

        def rotate() -> str | None:
            with factory() as db:
                barrier.wait(timeout=5)
                try:
                    return AuthService(db, settings).refresh(issued.refresh_token).access_token
                except AuthenticationError:
                    return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: rotate(), range(2)))
        winners = [token for token in outcomes if token is not None]
        assert len(winners) == 1
        with factory() as db:
            with pytest.raises(AuthenticationError):
                AuthService(db, settings).authenticate(winners[0])
            assert (
                db.scalar(select(AuthSession.revoked_at).where(AuthSession.user_id == user_id))
                is not None
            )
    finally:
        with factory() as db:
            sessions = select(AuthSession.id).where(AuthSession.user_id == user_id)
            db.execute(delete(RefreshToken).where(RefreshToken.session_id.in_(sessions)))
            db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
        engine.dispose()
