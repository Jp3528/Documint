"""At-least-once delivery; workers never trust a broker message to mark a version READY."""

import logging
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import Session

from packages.documents.models import DocumentVersion
from packages.identity.organization import ConflictError
from packages.identity.security import utcnow

from .models import ProcessingJob

logger = logging.getLogger(__name__)


def dispatch_pending(
    db: Session,
    publish: Callable[[UUID], None],
    limit: int = 25,
    *,
    only_job_ids: tuple[UUID, ...] | None = None,
) -> dict[str, int]:
    counts = {"queued": 0, "deferred": 0, "failed": 0}
    now = utcnow()
    ids = list(
        db.scalars(
            select(ProcessingJob.id)
            .where(
                or_(
                    and_(ProcessingJob.status == "PENDING", ProcessingJob.next_dispatch_at <= now),
                    and_(
                        ProcessingJob.status == "QUEUED",
                        ProcessingJob.queued_at < now - timedelta(minutes=5),
                    ),
                )
            )
            .where(ProcessingJob.id.in_(only_job_ids) if only_job_ids is not None else true())
            .order_by(ProcessingJob.created_at)
            .limit(limit)
        )
    )
    for job_id in ids:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            db.rollback()
            continue
        if job.status not in {"PENDING", "QUEUED"}:
            db.rollback()
            continue
        if (
            job.status == "QUEUED"
            and job.queued_at
            and job.queued_at >= utcnow() - timedelta(minutes=5)
        ):
            db.rollback()
            continue
        if job.status == "PENDING" and job.next_dispatch_at > utcnow():
            db.rollback()
            continue
        if job.dispatch_attempts >= 5:
            job.status, job.error_code = "DISPATCH_FAILED", "DISPATCH_LIMIT_REACHED"
            db.commit()
            counts["failed"] += 1
            continue
        job.dispatch_attempts += 1
        try:
            publish(job.id)
        except Exception as exc:
            job.error_code = "BROKER_UNAVAILABLE"
            job.status = "DISPATCH_FAILED" if job.dispatch_attempts >= 5 else "PENDING"
            job.next_dispatch_at = utcnow() + timedelta(seconds=min(300, 2**job.dispatch_attempts))
            logger.warning(
                "processing_publish_failed job_id=%s category=%s", job.id, type(exc).__name__
            )
            counts["failed" if job.status == "DISPATCH_FAILED" else "deferred"] += 1
        else:
            job.status, job.queued_at, job.error_code = "QUEUED", utcnow(), None
            version = db.get(DocumentVersion, job.version_id)
            if version and version.status == "UPLOADED":
                version.status = "QUEUED"
            counts["queued"] += 1
        db.commit()
    return counts


def process_job(db: Session, job_id: UUID) -> str:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
    if job is None:
        return "NOT_FOUND"
    if job.status not in {"PENDING", "QUEUED"}:
        return job.status
    # Phase 2C has no production parser/index runner. Acknowledge once, without retrying or lying.
    job.status, job.stage, job.error_code = "WAITING_PIPELINE", "WAITING_PIPELINE", None
    version = db.get(DocumentVersion, job.version_id)
    if version:
        version.status = "QUEUED"
    db.commit()
    return job.status


def retry_job(db: Session, job: ProcessingJob) -> ProcessingJob:
    if job.status in {"PENDING", "QUEUED", "RUNNING", "WAITING_PIPELINE"}:
        return job
    if job.status == "SUCCEEDED" or job.attempts >= job.max_attempts:
        raise ConflictError("El trabajo no admite más intentos")
    job.status, job.stage, job.error_code = "PENDING", "STORED", None
    job.dispatch_attempts, job.queued_at, job.next_dispatch_at = 0, None, utcnow()
    db.commit()
    return job
