from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database import Base


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint("version_id", "parser_revision"),
        CheckConstraint("block_count > 0 AND character_count > 0", name="counts_positive"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$' AND normalized_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"), index=True)
    parser_revision: Mapped[str] = mapped_column(String(128))
    source_sha256: Mapped[str] = mapped_column(String(64))
    normalized_sha256: Mapped[str] = mapped_column(String(64))
    block_count: Mapped[int] = mapped_column()
    character_count: Mapped[int] = mapped_column()
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
