from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.database import Base


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("version_id", "pipeline_key"),
        CheckConstraint(
            "status IN ('PENDING','QUEUED','RUNNING','WAITING_PIPELINE','SUCCEEDED',"
            "'FAILED','DISPATCH_FAILED')",
            name="status_valid",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_valid"),
        CheckConstraint("max_attempts BETWEEN 1 AND 5", name="max_attempts_valid"),
        CheckConstraint("dispatch_attempts BETWEEN 0 AND 5", name="dispatch_attempts_valid"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"), index=True)
    pipeline_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="PENDING", server_default="PENDING")
    stage: Mapped[str] = mapped_column(String(32), default="STORED", server_default="STORED")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(default=3, server_default="3")
    dispatch_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(48))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_dispatch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
