"""Prepare immutable chunks only. This command generates no embeddings and cannot mark READY."""

import argparse
from dataclasses import asdict
from uuid import UUID

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.documents.models import DocumentVersion
from packages.identity.organization import ConflictError, NotFoundError
from packages.indexing.chunking import ChunkConfig, ChunkingError, EmbeddingProfile
from packages.indexing.service import IndexService
from packages.parsers.service import ExtractionService
from packages.processing.models import ProcessingJob
from packages.providers.fake import FakeEmbeddingProvider
from packages.storage import S3Storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    settings = get_settings()
    engine, storage = make_engine(settings), S3Storage(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(ProcessingJob, args.job_id)
            if job is None:
                raise NotFoundError
            if job.status in {"RUNNING", "SUCCEEDED"}:
                raise ConflictError("El trabajo no admite esta etapa aislada")
            if job.stage != "CHUNKED":
                state = ExtractionService(db, storage, settings).run_stage(job.id)
                if state == "FAILED":
                    print("Chunking not started: extraction failed")
                    raise SystemExit(1)
            profile = EmbeddingProfile.model_validate(asdict(FakeEmbeddingProvider().model))
            config = ChunkConfig(
                max_characters=settings.chunk_max_characters,
                overlap_characters=settings.chunk_overlap_characters,
            )
            try:
                revision = IndexService(db, storage, settings).prepare(
                    job.version_id, config, profile
                )
            except ChunkingError as exc:
                db.rollback()
                job.status, job.stage, job.error_code = "FAILED", "CHUNKING", str(exc)
                version = db.get(DocumentVersion, job.version_id)
                if version and version.status != "READY":
                    version.status = "FAILED"
                db.commit()
                print("Chunking stage: FAILED")
                raise SystemExit(1) from None
            job.status, job.stage = "WAITING_PIPELINE", "CHUNKED"
            version = db.get(DocumentVersion, job.version_id)
            if version and version.status != "READY":
                version.status = "EMBEDDING"
            db.commit()
            print(
                f"Revision {revision.id}: {revision.chunk_count} chunks, CHUNKED, profile FAKE; "
                "no vectors generated"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
