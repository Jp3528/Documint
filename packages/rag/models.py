from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database import Base


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('ANSWERED','ABSTAINED','FAILED')", name="status_valid"),
        CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name="question_hash_valid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    question_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    model_info: Mapped[dict[str, Any]] = mapped_column(JSONB)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prompt_version: Mapped[str] = mapped_column(String(64))
    context_token_upper_bound: Mapped[int] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationSource(Base):
    __tablename__ = "generation_sources"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("generation_runs.id"), primary_key=True)
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("index_chunks.id"), primary_key=True)
    cited: Mapped[bool] = mapped_column(Boolean)
