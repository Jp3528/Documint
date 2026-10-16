"""Explicitly reconcile stale upload reservations; never delete historical evidence."""

import argparse
from datetime import timedelta

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.documents.models import DocumentVersion
from packages.documents.service import clean_failed_upload, reconcile_upload
from packages.identity.security import utcnow
from packages.storage import S3Storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-minutes", type=int, default=5)
    args = parser.parse_args()
    if args.older_than_minutes < 5:
        parser.error("reservations must be at least five minutes old")
    settings = get_settings()
    engine, storage = make_engine(settings), S3Storage(settings)
    restored = failed = deferred = cleaned = 0
    pending = or_(
        DocumentVersion.status == "UPLOADING",
        and_(
            DocumentVersion.status == "UPLOAD_FAILED",
            DocumentVersion.error_code == "STORAGE_WRITE_FAILED",
        ),
    )
    try:
        with Session(engine, expire_on_commit=False) as db:
            ids = list(
                db.scalars(
                    select(DocumentVersion.id)
                    .where(
                        pending,
                        DocumentVersion.created_at
                        < utcnow() - timedelta(minutes=args.older_than_minutes),
                    )
                    .limit(100)
                )
            )
            for version_id in ids:
                version = db.scalar(
                    select(DocumentVersion)
                    .where(DocumentVersion.id == version_id, pending)
                    .with_for_update(skip_locked=True)
                )
                if version is None:
                    db.rollback()
                    continue
                try:
                    if version.status == "UPLOAD_FAILED":
                        clean_failed_upload(db, storage, version)
                        cleaned += 1
                        continue
                    state = reconcile_upload(db, storage, version)
                except (BotoCoreError, ClientError, OSError):
                    db.rollback()
                    deferred += 1
                    continue
                restored += state == "UPLOADED"
                failed += state == "UPLOAD_FAILED"
        print(
            f"Uploads: {restored} restored, {failed} failed, {cleaned} cleaned, {deferred} deferred"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
