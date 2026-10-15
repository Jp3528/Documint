from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

from packages.identity.models import User
from packages.identity.organization import OrganizationService
from packages.identity.policies import RoleName

from .auth import UserProfile, build_profile
from .dependencies import get_organization_service

router = APIRouter(tags=["organization"])
type Service = Annotated[OrganizationService, Depends(get_organization_service)]
type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


class Pagination(BaseModel):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=25, ge=1, le=100)


type Params = Annotated[Pagination, Query()]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RolesInput(Input):
    roles: list[RoleName] = Field(
        default_factory=lambda: [RoleName.EMPLOYEE], min_length=1, max_length=4
    )

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[RoleName]) -> list[RoleName]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate role")
        return value


class UserInput(RolesInput):
    email: EmailStr
    display_name: Name
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class UserUpdate(Input):
    display_name: Name | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class DepartmentInput(Input):
    code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z][A-Z0-9_]{0,31}$"),
    ]
    name: Name

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class DepartmentUpdate(Input):
    name: Name | None = None
    active: bool | None = None


class DepartmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    active: bool


class MemberInput(Input):
    user_id: UUID
    membership_role: Literal["MEMBER", "MANAGER"] = "MEMBER"


class MemberView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    department_id: UUID
    membership_role: Literal["MEMBER", "MANAGER"]


def user_view(user: User, service: OrganizationService) -> UserProfile:
    return build_profile(user, service.db)


@router.get("/admin/users", response_model=Page[UserProfile])
def users(params: Params, service: Service) -> Page[UserProfile]:
    rows, total = service.list_users(params.offset, params.limit)
    return Page(
        items=[user_view(user, service) for user in rows], total=total, **params.model_dump()
    )


@router.get("/admin/users/{user_id}", response_model=UserProfile)
def user(user_id: UUID, service: Service) -> UserProfile:
    return user_view(service.user(user_id), service)


@router.post("/admin/users", response_model=UserProfile, status_code=201)
def create_user(payload: UserInput, service: Service) -> UserProfile:
    result = service.create_user(
        str(payload.email), payload.display_name, payload.password.get_secret_value(), payload.roles
    )
    return user_view(result, service)


@router.patch("/admin/users/{user_id}", response_model=UserProfile)
def update_user(user_id: UUID, payload: UserUpdate, service: Service) -> UserProfile:
    return user_view(service.update_user(user_id, payload.display_name, payload.status), service)


@router.get("/admin/roles", response_model=Page[str])
def roles(params: Params, service: Service) -> Page[str]:
    rows = service.list_roles()
    return Page(
        items=rows[params.offset : params.offset + params.limit],
        total=len(rows),
        **params.model_dump(),
    )


@router.put("/admin/users/{user_id}/roles", response_model=UserProfile)
def assign_roles(user_id: UUID, payload: RolesInput, service: Service) -> UserProfile:
    return user_view(service.assign_roles(user_id, payload.roles), service)


@router.get("/departments", response_model=Page[DepartmentView])
def departments(params: Params, service: Service) -> Page[DepartmentView]:
    rows, total = service.list_departments(params.offset, params.limit)
    return Page(
        items=[DepartmentView.model_validate(row) for row in rows],
        total=total,
        **params.model_dump(),
    )


@router.get("/departments/{department_id}", response_model=DepartmentView)
def department(department_id: UUID, service: Service) -> DepartmentView:
    return DepartmentView.model_validate(service.department(department_id))


@router.post("/departments", response_model=DepartmentView, status_code=201)
def create_department(payload: DepartmentInput, service: Service) -> DepartmentView:
    return DepartmentView.model_validate(service.create_department(payload.code, payload.name))


@router.patch("/departments/{department_id}", response_model=DepartmentView)
def update_department(
    department_id: UUID, payload: DepartmentUpdate, service: Service
) -> DepartmentView:
    return DepartmentView.model_validate(
        service.update_department(department_id, payload.name, payload.active)
    )


@router.get("/departments/{department_id}/memberships", response_model=Page[MemberView])
def members(department_id: UUID, params: Params, service: Service) -> Page[MemberView]:
    rows, total = service.list_members(department_id, params.offset, params.limit)
    return Page(
        items=[MemberView.model_validate(row) for row in rows], total=total, **params.model_dump()
    )


@router.post("/departments/{department_id}/memberships", response_model=MemberView, status_code=201)
def add_member(department_id: UUID, payload: MemberInput, service: Service) -> MemberView:
    return MemberView.model_validate(
        service.add_member(department_id, payload.user_id, payload.membership_role)
    )


@router.delete("/departments/{department_id}/memberships/{user_id}", status_code=204)
def remove_member(department_id: UUID, user_id: UUID, service: Service) -> None:
    service.remove_member(department_id, user_id)
