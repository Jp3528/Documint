import secrets
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.main import create_app
from packages.config import Settings
from packages.identity.security import (
    AuthConfigurationError,
    AuthenticationError,
    TokenCodec,
    hash_password,
    new_refresh,
    refresh_digest,
    verify_password,
)


def configured() -> Settings:
    return Settings(auth_secret=SecretStr(secrets.token_urlsafe(48)))


def test_argon2_passwords_are_salted_and_verified() -> None:
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert hash_password(password) != encoded
    assert verify_password(password, encoded) == (True, None)
    assert not verify_password("wrong", encoded)[0]
    assert not verify_password(password, None)[0]
    assert not verify_password(password, "invalid-hash")[0]
    with pytest.raises(ValueError):
        hash_password("short")


def test_access_contract_and_refresh_are_separate() -> None:
    settings = configured()
    codec = TokenCodec(settings)
    user_id, session_id = uuid4(), uuid4()
    first = codec.issue(user_id, session_id)
    claims = codec.decode(first)
    assert claims.sub == user_id and claims.sid == session_id
    assert claims.exp - claims.iat == 300
    assert codec.issue(user_id, session_id) != first
    raw = new_refresh()
    assert len(raw) >= 43 and len(refresh_digest(raw)) == 64
    assert raw != refresh_digest(raw)
    with pytest.raises(AuthenticationError):
        codec.decode(raw)


@pytest.mark.parametrize("mutation", ["expired", "issuer", "audience", "type", "missing", "future"])
def test_invalid_claims_are_rejected(mutation: str) -> None:
    settings = configured()
    codec = TokenCodec(settings)
    payload = codec.decode(codec.issue(uuid4(), uuid4())).model_dump(mode="json")
    if mutation == "expired":
        payload["exp"] = 1
    elif mutation == "issuer":
        payload["iss"] = "other"
    elif mutation == "audience":
        payload["aud"] = "other"
    elif mutation == "type":
        payload["type"] = "refresh"
    elif mutation == "missing":
        del payload["jti"]
    else:
        payload["iat"] += 3600
    assert settings.auth_secret is not None
    invalid = jwt.encode(payload, settings.auth_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(AuthenticationError):
        codec.decode(invalid)


def test_unsigned_wrong_signature_and_missing_configuration_fail_closed() -> None:
    codec = TokenCodec(configured())
    payload = codec.decode(codec.issue(uuid4(), uuid4())).model_dump(mode="json")
    for token in (
        jwt.encode(payload, key="", algorithm="none"),
        jwt.encode(payload, key=secrets.token_urlsafe(48), algorithm="HS256"),
    ):
        with pytest.raises(AuthenticationError):
            codec.decode(token)
    with pytest.raises(AuthConfigurationError):
        TokenCodec(Settings(auth_secret=SecretStr("")))


def test_csrf_validation_and_missing_bearer_need_no_database() -> None:
    with TestClient(create_app(configured())) as client:
        assert client.get("/me").status_code == 401
        assert client.post("/auth/logout").status_code == 403
        assert (
            client.post(
                "/auth/logout",
                headers={"X-DocuMind-CSRF": "1", "Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )


def test_validation_does_not_echo_passwords() -> None:
    private_input = secrets.token_urlsafe(128)
    with TestClient(create_app(configured())) as client:
        response = client.post(
            "/auth/login",
            headers={"X-DocuMind-CSRF": "1"},
            json={
                "email": "broken",
                "password": private_input,
            },
        )
    assert response.status_code == 422
    assert private_input not in response.text
    assert response.headers["cache-control"] == "no-store"
