"""Durable upload reservations avoid unreferenced objects across database/S3 failures."""

import hashlib
import logging
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from packages.identity.organization import ForbiddenError, NotFoundError
from packages.identity.policies import Action, Actor, permits
from packages.storage import ObjectStorage

from .access import document_access
from .models import Document, DocumentVersion
from .validation import ValidatedUpload

logger = logging.getLogger(__name__)


class UploadUnavailable(Exception):
    pass


class DocumentService:
    def __init__(self, db: Session, actor: Actor, storage: ObjectStorage) -> None:
        self.db, self.actor, self.storage = db, actor, storage

    def require_upload(self) -> None:
        if not permits(self.actor, Action.MANAGE_KNOWLEDGE):
            raise ForbiddenError

    def create(self, upload: ValidatedUpload) -> tuple[Document, DocumentVersion]:
        self.require_upload()
        document = Document(id=uuid4(), owner_id=self.actor.id, title=upload.filename)
        self.db.add(document)
        self.db.flush()
        return self.store_original(document, upload, 1)

    def store_original(
        self, document: Document, upload: ValidatedUpload, number: int
    ) -> tuple[Document, DocumentVersion]:
        version_id = uuid4()
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            version_number=number,
            uploaded_by=self.actor.id,
            filename=upload.filename,
            media_type=upload.media_type,
            size_bytes=len(upload.content),
            sha256=upload.sha256,
            object_key=f"documents/{document.id}/versions/{version_id}/original",
        )
        self.db.add(version)
        self.db.commit()  # A durable reservation exists before any S3 side effect.
        try:
            self.storage.put(version.object_key, upload.content, upload.media_type)
        except (BotoCoreError, ClientError, OSError) as exc:
            # PUT may have succeeded before a timeout. Keep metadata even if cleanup fails.
            try:
                self.storage.delete(version.object_key)
            except (BotoCoreError, ClientError, OSError):
                logger.warning("upload_cleanup_pending version_id=%s", version.id)
            version.status, version.error_code = "UPLOAD_FAILED", "STORAGE_WRITE_FAILED"
            self.db.commit()
            raise UploadUnavailable from exc
        version.status = "UPLOADED"
        try:
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()  # Reservation remains UPLOADING and can be reconciled.
            raise UploadUnavailable from exc
        return document, version

    def version(self, document_id: UUID, version_id: UUID) -> tuple[Document, DocumentVersion]:
        document = self.document(document_id)
        version = self.db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id, DocumentVersion.document_id == document_id
            )
        )
        if version is None:
            raise NotFoundError
        return document, version

    def document(self, document_id: UUID, *, manage: bool = False) -> Document:
        query = select(Document).where(
            Document.id == document_id, document_access(self.actor, manage=manage)
        )
        if manage:
            query = query.with_for_update()
        document = self.db.scalar(query)
        if document is None:
            raise NotFoundError
        return document

    def new_version(
        self, document_id: UUID, upload: ValidatedUpload
    ) -> tuple[Document, DocumentVersion]:
        document = self.document(document_id, manage=True)
        number = (
            self.db.scalar(
                select(func.max(DocumentVersion.version_number)).where(
                    DocumentVersion.document_id == document_id
                )
            )
            or 0
        )
        return self.store_original(document, upload, number + 1)


def reconcile_upload(db: Session, storage: ObjectStorage, version: DocumentVersion) -> str:
    """Trusted maintenance only; a missing object is distinct from a transient S3 failure."""
    if version.status != "UPLOADING":
        raise ValueError("only pending upload reservations can be reconciled")
    try:
        content = storage.get(version.object_key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404", "NotFound"}:
            raise
        version.status, version.error_code = "UPLOAD_FAILED", "STORAGE_MISSING"
    else:
        if (
            len(content) == version.size_bytes
            and hashlib.sha256(content).hexdigest() == version.sha256
        ):
            version.status, version.error_code = "UPLOADED", None
        else:
            version.status, version.error_code = "UPLOAD_FAILED", "STORAGE_INTEGRITY_FAILED"
    db.commit()
    return version.status


def clean_failed_upload(db: Session, storage: ObjectStorage, version: DocumentVersion) -> None:
    if version.status != "UPLOAD_FAILED" or version.error_code != "STORAGE_WRITE_FAILED":
        raise ValueError("only failed upload writes can be cleaned")
    storage.delete(version.object_key)
    version.error_code = "STORAGE_CLEANED"
    db.commit()
