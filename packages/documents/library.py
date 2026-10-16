from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.identity.models import Department, User
from packages.identity.organization import ConflictError, NotFoundError
from packages.identity.policies import DocumentScope, RoleName, can_manage_document

from .access import document_access
from .models import Document, DocumentGrant, DocumentVersion
from .service import DocumentService


class LibraryService(DocumentService):
    def list_documents(
        self, offset: int, limit: int, include_archived: bool
    ) -> tuple[list[Document], int]:
        query = select(Document).where(document_access(self.actor))
        if not include_archived:
            query = query.where(Document.archived.is_(False))
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            self.db.scalars(
                query.order_by(Document.created_at.desc(), Document.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    def latest_version(self, document_id: UUID) -> DocumentVersion | None:
        return self.db.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )

    def list_versions(
        self, document_id: UUID, offset: int, limit: int
    ) -> tuple[Document, list[DocumentVersion], int]:
        document = self.document(document_id)
        query = select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            self.db.scalars(
                query.order_by(DocumentVersion.version_number.desc()).offset(offset).limit(limit)
            )
        )
        return document, rows, total

    def may_manage(self, document: Document) -> bool:
        grants = list(
            self.db.scalars(select(DocumentGrant).where(DocumentGrant.document_id == document.id))
        )
        return can_manage_document(
            self.actor,
            DocumentScope(
                document.owner_id,
                document.department_id,
                document.visibility,
                frozenset(g.user_id for g in grants if g.user_id),
                frozenset(RoleName(g.role_name) for g in grants if g.role_name),
                frozenset(g.user_id for g in grants if g.user_id and g.permission == "MANAGE"),
                frozenset(
                    RoleName(g.role_name)
                    for g in grants
                    if g.role_name and g.permission == "MANAGE"
                ),
            ),
        )

    def update_document(self, document_id: UUID, changes: dict[str, object]) -> Document:
        document = self.document(document_id, manage=True)
        department_id = changes.get("department_id", document.department_id)
        visibility = changes.get("visibility", document.visibility)
        if visibility == "DEPARTMENT" and department_id is None:
            raise ConflictError("La visibilidad de departamento requiere un departamento")
        if department_id is not None and ({"department_id", "visibility"} & changes.keys()):
            department = self.db.get(Department, department_id)
            if (
                department is None
                or not department.active
                or (
                    RoleName.ADMIN not in self.actor.roles
                    and department.id not in self.actor.departments
                    and department.id != document.department_id
                )
            ):
                raise NotFoundError
        for key, value in changes.items():
            setattr(document, key, value)
        self.db.commit()
        return document

    def list_grants(
        self, document_id: UUID, offset: int, limit: int
    ) -> tuple[list[DocumentGrant], int]:
        self.document(document_id, manage=True)
        query = select(DocumentGrant).where(DocumentGrant.document_id == document_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            self.db.scalars(
                query.order_by(DocumentGrant.created_at, DocumentGrant.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    def add_grant(
        self, document_id: UUID, user_id: UUID | None, role: RoleName | None, permission: str
    ) -> DocumentGrant:
        self.document(document_id, manage=True)
        if user_id is not None:
            subject = self.db.get(User, user_id)
            if subject is None or subject.status != "ACTIVE":
                raise NotFoundError
        grant = DocumentGrant(
            document_id=document_id,
            user_id=user_id,
            role_name=role,
            permission=permission,
            granted_by=self.actor.id,
        )
        self.db.add(grant)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("Ya existe un permiso para ese destinatario") from exc
        return grant

    def remove_grant(self, document_id: UUID, grant_id: UUID) -> None:
        self.document(document_id, manage=True)
        grant = self.db.get(DocumentGrant, grant_id)
        if grant is None or grant.document_id != document_id:
            raise NotFoundError
        self.db.delete(grant)
        self.db.commit()
