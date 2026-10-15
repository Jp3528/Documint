from typing import Literal
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuthSession, Department, DepartmentMember, Role, User, UserRole
from .policies import Action, Actor, RoleName, can_view_department, permits
from .security import hash_password, utcnow


class ForbiddenError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def load_actor(db: Session, user: User) -> Actor:
    roles = frozenset(
        RoleName(name)
        for name in db.scalars(select(UserRole.role_name).where(UserRole.user_id == user.id))
    )
    departments = frozenset(
        db.scalars(
            select(DepartmentMember.department_id)
            .join(Department)
            .where(DepartmentMember.user_id == user.id, Department.active.is_(True))
        )
    )
    return Actor(user.id, user.status == "ACTIVE", roles, departments)


class OrganizationService:
    def __init__(self, db: Session, actor: Actor) -> None:
        self.db, self.actor = db, actor

    def require(self, action: Action) -> None:
        if not permits(self.actor, action):
            raise ForbiddenError

    def commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("El recurso ya existe o infringe una restricción") from exc

    def list_users(self, offset: int, limit: int) -> tuple[list[User], int]:
        self.require(Action.MANAGE_USERS)
        total = self.db.scalar(select(func.count()).select_from(User)) or 0
        users = list(
            self.db.scalars(select(User).order_by(User.email, User.id).offset(offset).limit(limit))
        )
        return users, total

    def user(self, user_id: UUID) -> User:
        self.require(Action.MANAGE_USERS)
        target = self.db.get(User, user_id)
        if target is None:
            raise NotFoundError
        return target

    def _role_lock(self) -> None:
        # Serialize changes to active ADMIN membership to avoid concurrent lockout.
        self.db.scalar(select(Role).where(Role.name == RoleName.ADMIN).with_for_update())

    def _protect_last_admin(self, target: User, roles: list[RoleName], status: str) -> None:
        current = self.db.scalar(
            select(UserRole).where(
                UserRole.user_id == target.id, UserRole.role_name == RoleName.ADMIN
            )
        )
        removing = target.status == "ACTIVE" and (status != "ACTIVE" or RoleName.ADMIN not in roles)
        if current and removing:
            count = (
                self.db.scalar(
                    select(func.count())
                    .select_from(UserRole)
                    .join(User)
                    .where(UserRole.role_name == RoleName.ADMIN, User.status == "ACTIVE")
                )
                or 0
            )
            if count <= 1:
                raise ConflictError("Debe quedar al menos un administrador activo")

    def create_user(self, email: str, name: str, password: str, roles: list[RoleName]) -> User:
        self.require(Action.MANAGE_USERS)
        self._role_lock()
        user = User(email=email, display_name=name, password_hash=hash_password(password))
        self.db.add(user)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("El usuario ya existe") from exc
        self.db.add_all(UserRole(user_id=user.id, role_name=role) for role in roles)
        self.commit()
        return user

    def update_user(
        self, user_id: UUID, name: str | None, status: Literal["ACTIVE", "INACTIVE"] | None
    ) -> User:
        self.require(Action.MANAGE_USERS)
        self._role_lock()
        target = self.user(user_id)
        roles = [
            RoleName(role)
            for role in self.db.scalars(
                select(UserRole.role_name).where(UserRole.user_id == user_id)
            )
        ]
        self._protect_last_admin(target, roles, status or target.status)
        if name is not None:
            target.display_name = name
        if status is not None:
            target.status = status
            if status == "INACTIVE":
                self.db.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=utcnow())
                )
        self.commit()
        return target

    def assign_roles(self, user_id: UUID, roles: list[RoleName]) -> User:
        self.require(Action.MANAGE_USERS)
        self._role_lock()
        target = self.user(user_id)
        self._protect_last_admin(target, roles, target.status)
        self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self.db.add_all(UserRole(user_id=user_id, role_name=role) for role in roles)
        self.commit()
        return target

    def list_roles(self) -> list[str]:
        self.require(Action.MANAGE_USERS)
        return list(self.db.scalars(select(Role.name).order_by(Role.name)))

    def list_departments(self, offset: int, limit: int) -> tuple[list[Department], int]:
        if not self.actor.active:
            raise ForbiddenError
        query = select(Department)
        if not permits(self.actor, Action.MANAGE_DEPARTMENTS):
            query = query.where(
                Department.id.in_(self.actor.departments), Department.active.is_(True)
            )
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(self.db.scalars(query.order_by(Department.code).offset(offset).limit(limit)))
        return rows, total

    def department(self, department_id: UUID) -> Department:
        department = self.db.get(Department, department_id)
        if department is None or not can_view_department(
            self.actor, department_id, active=department.active
        ):
            raise NotFoundError
        return department

    def create_department(self, code: str, name: str) -> Department:
        self.require(Action.MANAGE_DEPARTMENTS)
        department = Department(code=code, name=name)
        self.db.add(department)
        self.commit()
        return department

    def update_department(
        self, department_id: UUID, name: str | None, active: bool | None
    ) -> Department:
        self.require(Action.MANAGE_DEPARTMENTS)
        department = self.department(department_id)
        if name is not None:
            department.name = name
        if active is not None:
            department.active = active
        self.commit()
        return department

    def list_members(
        self, department_id: UUID, offset: int, limit: int
    ) -> tuple[list[DepartmentMember], int]:
        self.require(Action.MANAGE_DEPARTMENTS)
        self.department(department_id)
        query = select(DepartmentMember).where(DepartmentMember.department_id == department_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            self.db.scalars(query.order_by(DepartmentMember.user_id).offset(offset).limit(limit))
        )
        return rows, total

    def add_member(
        self, department_id: UUID, user_id: UUID, membership_role: str
    ) -> DepartmentMember:
        self.require(Action.MANAGE_DEPARTMENTS)
        self.department(department_id)
        if self.db.get(User, user_id) is None:
            raise NotFoundError
        member = DepartmentMember(
            department_id=department_id, user_id=user_id, membership_role=membership_role
        )
        self.db.add(member)
        self.commit()
        return member

    def remove_member(self, department_id: UUID, user_id: UUID) -> None:
        self.require(Action.MANAGE_DEPARTMENTS)
        self.department(department_id)
        member = self.db.get(DepartmentMember, (department_id, user_id))
        if member is None:
            raise NotFoundError
        self.db.delete(member)
        self.commit()
