from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from packages.config import Settings
from packages.identity.models import User
from packages.identity.security import AuthConfigurationError, AuthenticationError
from packages.identity.service import AuthService

bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as db:
        yield db


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_auth_service(
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthService:
    return AuthService(db, settings)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None:
        raise HTTPException(401, "Sesión no válida", headers={"WWW-Authenticate": "Bearer"})
    try:
        return service.authenticate(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            401, "Sesión no válida", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(503, "Autenticación no disponible") from exc
