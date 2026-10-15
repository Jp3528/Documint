from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.identity.models import Department, DepartmentMember, User
from packages.identity.organization import load_actor
from packages.identity.policies import RoleName, capabilities
from packages.identity.security import AuthConfigurationError, AuthenticationError
from packages.identity.service import AuthService, IssuedSession

from .dependencies import current_user, get_app_settings, get_auth_service, get_session

COOKIE_NAME = "documind_refresh"


def require_csrf(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("x-documind-csrf") != "1" or (
        origin is not None and origin not in settings.web_origins
    ):
        raise HTTPException(403, "Solicitud no permitida")


router = APIRouter(prefix="/auth", tags=["identity"], dependencies=[Depends(require_csrf)])
profile_router = APIRouter(tags=["identity"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ProfileDepartment(BaseModel):
    id: UUID
    code: str
    name: str
    membership_role: str


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str
    status: Literal["ACTIVE", "INACTIVE"]
    roles: list[RoleName] = Field(default_factory=list)
    departments: list[ProfileDepartment] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)


def build_profile(user: User, db: Session) -> UserProfile:
    actor = load_actor(db, user)
    memberships = db.execute(
        select(Department, DepartmentMember.membership_role)
        .join(DepartmentMember, DepartmentMember.department_id == Department.id)
        .where(DepartmentMember.user_id == user.id, Department.active.is_(True))
        .order_by(Department.code)
    )
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=sorted(actor.roles),
        capabilities=capabilities(actor),
        departments=[
            ProfileDepartment(
                id=department.id, code=department.code, name=department.name, membership_role=role
            )
            for department, role in memberships
        ],
    )


def token_response(issued: IssuedSession, response: Response, settings: Settings) -> TokenResponse:
    response.set_cookie(
        COOKIE_NAME,
        issued.refresh_token,
        max_age=issued.refresh_expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/auth",
    )
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> TokenResponse:
    try:
        issued = service.login(str(payload.email), payload.password.get_secret_value())
    except AuthenticationError as exc:
        raise HTTPException(
            401, "Credenciales inválidas", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(503, "Autenticación no disponible") from exc
    return token_response(issued, response, settings)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> TokenResponse | JSONResponse:
    raw = request.cookies.get(COOKIE_NAME)
    try:
        if not raw or len(raw) > 256:
            raise AuthenticationError
        issued = service.refresh(raw)
    except AuthenticationError:
        failure = JSONResponse(
            {"detail": "Sesión no válida"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
        )
        failure.delete_cookie(
            COOKIE_NAME,
            path="/auth",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return failure
    except AuthConfigurationError as exc:
        raise HTTPException(503, "Autenticación no disponible") from exc
    return token_response(issued, response, settings)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    raw = request.cookies.get(COOKIE_NAME)
    service.logout(raw if raw and len(raw) <= 256 else None)
    response.delete_cookie(
        COOKIE_NAME, path="/auth", secure=settings.cookie_secure, httponly=True, samesite="strict"
    )


@profile_router.get("/me", response_model=UserProfile)
def profile(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> UserProfile:
    return build_profile(user, db)
