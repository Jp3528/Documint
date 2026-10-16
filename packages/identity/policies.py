"""Pure authorization decisions, independent of routers, database queries and JWT claims."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RoleName(StrEnum):
    ADMIN = "ADMIN"
    KNOWLEDGE_MANAGER = "KNOWLEDGE_MANAGER"
    EMPLOYEE = "EMPLOYEE"
    AUDITOR = "AUDITOR"


class Action(StrEnum):
    MANAGE_USERS = "manage_users"
    MANAGE_DEPARTMENTS = "manage_departments"
    VIEW_AUDIT = "view_audit"
    MANAGE_KNOWLEDGE = "manage_knowledge"


@dataclass(frozen=True)
class Actor:
    id: UUID
    active: bool
    roles: frozenset[RoleName]
    departments: frozenset[UUID] = frozenset()


@dataclass(frozen=True)
class DocumentScope:
    """Scope contract only. Persisted document/grant queries are implemented in phase 2."""

    owner_id: UUID
    department_id: UUID | None
    visibility: str
    read_users: frozenset[UUID] = frozenset()
    read_roles: frozenset[RoleName] = frozenset()
    manage_users: frozenset[UUID] = frozenset()
    manage_roles: frozenset[RoleName] = frozenset()


def permits(actor: Actor, action: Action) -> bool:
    if not actor.active:
        return False
    if RoleName.ADMIN in actor.roles:
        return True
    if action == Action.VIEW_AUDIT:
        return RoleName.AUDITOR in actor.roles
    if action == Action.MANAGE_KNOWLEDGE:
        return RoleName.KNOWLEDGE_MANAGER in actor.roles
    return False


def can_view_department(actor: Actor, department_id: UUID, *, active: bool = True) -> bool:
    return actor.active and (
        RoleName.ADMIN in actor.roles or (active and department_id in actor.departments)
    )


def can_read_document(actor: Actor, document: DocumentScope) -> bool:
    if not actor.active:
        return False
    if RoleName.ADMIN in actor.roles:
        return True
    if (
        actor.id == document.owner_id
        or actor.id in document.read_users
        or bool(actor.roles & document.read_roles)
        or actor.id in document.manage_users
        or bool(actor.roles & document.manage_roles)
    ):
        return True
    functional = actor.roles & {RoleName.EMPLOYEE, RoleName.KNOWLEDGE_MANAGER}
    if not functional:
        return False
    return document.visibility == "COMPANY" or (
        document.visibility == "DEPARTMENT" and document.department_id in actor.departments
    )


def capabilities(actor: Actor) -> dict[str, bool]:
    return {action.value: permits(actor, action) for action in Action}


def can_manage_document(actor: Actor, document: DocumentScope) -> bool:
    return actor.active and (
        RoleName.ADMIN in actor.roles
        or actor.id == document.owner_id
        or actor.id in document.manage_users
        or bool(actor.roles & document.manage_roles)
        or (
            RoleName.KNOWLEDGE_MANAGER in actor.roles
            and document.department_id in actor.departments
            and document.visibility in {"COMPANY", "DEPARTMENT"}
        )
    )
