"""Reusable SQL predicates: ACL is applied before count, ordering and pagination."""

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from packages.identity.policies import Actor, RoleName

from .models import Document, DocumentGrant


def document_access(actor: Actor, *, manage: bool = False) -> ColumnElement[bool]:
    if not actor.active:
        return false()
    if RoleName.ADMIN in actor.roles:
        return true()
    subject = or_(DocumentGrant.user_id == actor.id, DocumentGrant.role_name.in_(actor.roles))
    explicit = (
        select(DocumentGrant.id)
        .where(DocumentGrant.document_id == Document.id, subject)
        .correlate(Document)
    )
    if manage:
        explicit = explicit.where(DocumentGrant.permission == "MANAGE")
        implicit = (
            and_(
                Document.department_id.in_(actor.departments),
                Document.visibility.in_(["COMPANY", "DEPARTMENT"]),
            )
            if RoleName.KNOWLEDGE_MANAGER in actor.roles
            else false()
        )
    else:
        implicit = (
            or_(
                Document.visibility == "COMPANY",
                and_(
                    Document.visibility == "DEPARTMENT",
                    Document.department_id.in_(actor.departments),
                ),
            )
            if actor.roles & {RoleName.EMPLOYEE, RoleName.KNOWLEDGE_MANAGER}
            else false()
        )
    return or_(Document.owner_id == actor.id, explicit.exists(), implicit)
