from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.documents.models import DocumentVersion
from packages.identity.organization import NotFoundError
from packages.indexing.models import IndexRevision
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import retry_job

from .documents import Service
from .organization import Page, Params

router = APIRouter(prefix="/documents", tags=["processing"])


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_id: UUID
    pipeline_key: str
    status: str
    stage: str
    attempts: int
    max_attempts: int
    dispatch_attempts: int
    error_code: str | None
    index_revision_id: UUID | None
    embedding_mode: Literal["FAKE", "REAL"] | None = None
    created_at: datetime
    updated_at: datetime


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def job_view(job: ProcessingJob, db: Session) -> JobView:
    result = JobView.model_validate(job)
    revision = db.get(IndexRevision, job.index_revision_id) if job.index_revision_id else None
    if revision:
        result.embedding_mode = revision.embedding_profile["mode"]
    return result


@router.get("/{document_id}/versions/{version_id}/jobs", response_model=Page[JobView])
def list_jobs(
    document_id: UUID, version_id: UUID, params: Params, service: Service
) -> Page[JobView]:
    service.version(document_id, version_id)
    query = select(ProcessingJob).where(ProcessingJob.version_id == version_id)
    total = service.db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = service.db.scalars(
        query.order_by(ProcessingJob.created_at.desc(), ProcessingJob.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    return Page(
        items=[job_view(row, service.db) for row in rows], total=total, **params.model_dump()
    )


@router.post("/{document_id}/versions/{version_id}/jobs", status_code=202, response_model=JobView)
def enqueue(
    document_id: UUID,
    version_id: UUID,
    service: Service,
    payload: Annotated[EmptyInput | None, Body()] = None,
) -> JobView:
    service.document(document_id, manage=True)
    _, version = service.version(document_id, version_id)
    if version.status in {"UPLOADING", "UPLOAD_FAILED"}:
        raise HTTPException(409, "Primero debe completarse la carga del original")
    job = ensure_job(service.db, version_id, service.pipeline_key)
    service.db.commit()
    return job_view(job, service.db)


@router.post("/{document_id}/jobs/{job_id}/retry", status_code=202, response_model=JobView)
def retry(
    document_id: UUID,
    job_id: UUID,
    service: Service,
    payload: Annotated[EmptyInput | None, Body()] = None,
) -> JobView:
    service.document(document_id, manage=True)
    job = service.db.scalar(
        select(ProcessingJob)
        .join(DocumentVersion)
        .where(ProcessingJob.id == job_id, DocumentVersion.document_id == document_id)
        .with_for_update(of=ProcessingJob)
    )
    if job is None:
        raise NotFoundError
    return job_view(retry_job(service.db, job), service.db)
