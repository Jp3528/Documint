from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('COMPANY', 'DEPARTMENT', 'RESTRICTED')", name="visibility_valid"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    title: Mapped[str] = mapped_column(String(180))
    visibility: Mapped[str] = mapped_column(
        String(16), default="RESTRICTED", server_default="RESTRICTED"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        CheckConstraint("version_number > 0", name="version_positive"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_valid"),
        CheckConstraint(
            "status IN ('UPLOADING','UPLOAD_FAILED','UPLOADED','QUEUED','EXTRACTING',"
            "'CHUNKING','EMBEDDING','INDEXING','READY','FAILED')",
            name="status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    version_number: Mapped[int] = mapped_column()
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(180))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(256), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="UPLOADING", server_default="UPLOADING")
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
