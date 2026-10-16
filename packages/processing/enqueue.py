from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProcessingJob


def ensure_job(db: Session, version_id: UUID, pipeline_key: str) -> ProcessingJob:
    """Caller holds the document/version lock and commits together with the stored original."""
    existing = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.version_id == version_id, ProcessingJob.pipeline_key == pipeline_key
        )
    )
    if existing:
        return existing
    job = ProcessingJob(version_id=version_id, pipeline_key=pipeline_key)
    db.add(job)
    db.flush()
    return job
