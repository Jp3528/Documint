import hashlib
import logging
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.documents.models import DocumentVersion
from packages.identity.organization import ConflictError, NotFoundError
from packages.processing.models import ProcessingJob
from packages.storage import ObjectStorage

from .contracts import ParserError, TextBlock
from .models import Extraction
from .registry import ParserRegistry, normalized_digest

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, db: Session, storage: ObjectStorage, settings: Settings) -> None:
        self.db, self.storage, self.settings = db, storage, settings
        self.registry = ParserRegistry(settings)

    def extract_version(self, version_id: UUID) -> Extraction:
        version = self.db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError
        revision = self.registry.revision_for(version.filename)
        query = select(Extraction).where(
            Extraction.version_id == version_id, Extraction.parser_revision == revision
        )
        cached = self.db.scalar(query)
        if cached:
            if cached.source_sha256 != version.sha256:
                raise ParserError("STORAGE_INTEGRITY_FAILED")
            if (
                cached.character_count > self.settings.parser_max_characters
                or cached.block_count > self.settings.parser_max_blocks
            ):
                raise ParserError("EXTRACTION_LIMIT")
            try:
                blocks = tuple(TextBlock.model_validate(value) for value in cached.blocks)
            except ValidationError as exc:
                raise ParserError("EXTRACTION_INTEGRITY_FAILED") from exc
            if cached.block_count != len(blocks) or cached.character_count != sum(
                len(block.text) for block in blocks
            ):
                raise ParserError("EXTRACTION_INTEGRITY_FAILED")
            if cached.normalized_sha256 != normalized_digest(blocks) or [
                block.index for block in blocks
            ] != list(range(len(blocks))):
                raise ParserError("EXTRACTION_INTEGRITY_FAILED")
            return cached
        try:
            content = self.storage.get(version.object_key)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ParserError("STORAGE_READ_FAILED") from exc
        if (
            len(content) != version.size_bytes
            or hashlib.sha256(content).hexdigest() != version.sha256
        ):
            raise ParserError("STORAGE_INTEGRITY_FAILED")
        parsed = self.registry.parse(version.filename, content)
        self.db.execute(
            insert(Extraction)
            .values(
                id=uuid4(),
                version_id=version_id,
                parser_revision=parsed.parser_revision,
                source_sha256=parsed.source_sha256,
                normalized_sha256=parsed.normalized_sha256,
                block_count=len(parsed.blocks),
                character_count=parsed.character_count,
                blocks=[block.model_dump(mode="json") for block in parsed.blocks],
            )
            .on_conflict_do_nothing(index_elements=["version_id", "parser_revision"])
        )
        self.db.commit()
        stored = self.db.scalar(query)
        assert stored is not None
        if stored.normalized_sha256 != parsed.normalized_sha256:
            raise ParserError("PARSER_NON_DETERMINISTIC")
        return stored

    def run_stage(self, job_id: UUID) -> str:
        job = self.db.scalar(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        )
        if job is None:
            raise NotFoundError
        if job.status in {"RUNNING", "SUCCEEDED"}:
            return job.status
        if job.status == "WAITING_PIPELINE" and job.stage == "EXTRACTED":
            return job.status
        if job.attempts >= job.max_attempts:
            raise ConflictError("El trabajo agotó sus intentos")
        version = self.db.get(DocumentVersion, job.version_id)
        if version is None or version.status in {"UPLOADING", "UPLOAD_FAILED", "READY"}:
            raise ConflictError("La versión no admite esta etapa aislada")
        job.status, job.stage, job.error_code = "RUNNING", "EXTRACTING", None
        job.attempts += 1
        version.status = "EXTRACTING"
        self.db.commit()
        try:
            self.extract_version(version.id)
        except ParserError as exc:
            self.db.rollback()
            job.status, job.stage, job.error_code = "FAILED", "EXTRACTING", exc.code
            version.status = "FAILED"
            logger.warning("extraction_failed job_id=%s code=%s", job.id, exc.code)
        else:
            job.status, job.stage, job.error_code = "WAITING_PIPELINE", "EXTRACTED", None
            version.status = "CHUNKING"
        self.db.commit()
        return job.status
