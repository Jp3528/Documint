"""Complete worker pipeline with bounded attempts and expiring, fenced ownership."""

import logging
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.documents.models import DocumentVersion
from packages.identity.security import utcnow
from packages.indexing.chunking import ChunkConfig, ChunkingError
from packages.indexing.service import IndexService
from packages.parsers.contracts import ParserError
from packages.parsers.service import ExtractionService
from packages.providers.contracts import EmbeddingProvider, ProviderError
from packages.providers.factory import make_embedding_provider
from packages.providers.validation import embedding_profile
from packages.storage import ObjectStorage, S3Storage

from .models import ProcessingJob

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)


class LeaseLost(Exception):
    pass


def process_pipeline(
    db: Session,
    job_id: UUID,
    settings: Settings,
    *,
    storage: ObjectStorage | None = None,
    provider: EmbeddingProvider | None = None,
) -> str:
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        return "NOT_FOUND"
    if job.status == "RUNNING" and job.lease_expires_at and job.lease_expires_at > utcnow():
        db.rollback()
        return "RUNNING"
    if job.status not in {"PENDING", "QUEUED", "WAITING_PIPELINE", "RUNNING"}:
        state = job.status
        db.rollback()
        return state
    if job.attempts >= job.max_attempts:
        job.status, job.error_code = "FAILED", "EXECUTION_LIMIT_REACHED"
        job.run_token, job.lease_expires_at = None, None
        version = db.get(DocumentVersion, job.version_id)
        if version and version.status != "READY":
            version.status = "FAILED"
        db.commit()
        return "FAILED"
    token = uuid4()
    job.run_token, job.lease_expires_at = token, utcnow() + LEASE
    job.status, job.error_code = "RUNNING", None
    job.attempts += 1
    version_id = job.version_id
    db.commit()

    def fence() -> None:
        current = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current is None
            or current.run_token != token
            or current.status != "RUNNING"
            or current.lease_expires_at is None
            or current.lease_expires_at <= utcnow()
        ):
            raise LeaseLost
        current.lease_expires_at = utcnow() + LEASE

    def stage(name: str) -> None:
        fence()
        job.stage = name
        version = db.get(DocumentVersion, version_id)
        if version is None or version.status in {"UPLOADING", "UPLOAD_FAILED"}:
            raise ParserError("ORIGINAL_NOT_STORED")
        if version.status != "READY":
            version.status = name
        db.commit()

    try:
        embedding = provider if provider is not None else make_embedding_provider(settings)
        original = storage if storage is not None else S3Storage(settings)
        stage("EXTRACTING")
        ExtractionService(db, original, settings).extract_version(version_id)
        stage("CHUNKING")
        index = IndexService(db, original, settings)
        revision = index.prepare(
            version_id,
            ChunkConfig(
                max_characters=settings.chunk_max_characters,
                overlap_characters=settings.chunk_overlap_characters,
            ),
            embedding_profile(embedding.model),
        )
        fence()
        job.index_revision_id = revision.id
        db.commit()
        stage("EMBEDDING")
        index.embed(revision.id, embedding, fence)
        stage("INDEXING")
        fence()
        index.activate(revision.id, commit=False)
        job.status, job.stage, job.error_code = "SUCCEEDED", "INDEXED", None
        job.run_token, job.lease_expires_at = None, None
        db.commit()  # READY, active revision and successful job are one transaction.
        return "SUCCEEDED"
    except LeaseLost:
        db.rollback()
        return "LEASE_LOST"
    except Exception as exc:
        db.rollback()
        try:
            fence()  # A replaced worker may not change even failure state.
        except LeaseLost:
            db.rollback()
            return "LEASE_LOST"
        code = (
            exc.code
            if isinstance(exc, (ProviderError, ParserError))
            else str(exc)
            if isinstance(exc, ChunkingError)
            else "PIPELINE_FAILED"
        )
        job.status, job.error_code = "FAILED", code
        job.run_token, job.lease_expires_at = None, None
        version = db.get(DocumentVersion, version_id)
        if version and version.status != "READY":
            version.status = "FAILED"
        db.commit()
        logger.warning(
            "processing_failed job_id=%s code=%s category=%s", job_id, code, type(exc).__name__
        )
        return "FAILED"
