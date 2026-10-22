"""Import only the checked synthetic corpus; never reset existing documents or permissions."""

import argparse
import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from evals.schema import Manifest
from packages.config import Settings, get_settings
from packages.database import make_engine
from packages.documents.models import Document, DocumentGrant, DocumentVersion
from packages.documents.service import DocumentService
from packages.documents.validation import validate_upload
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.processing.enqueue import ensure_job
from packages.processing.service import process_job
from packages.storage import ObjectStorage, S3Storage
from scripts.seed_demo import demo_personas, seed_identities

ROOT = Path(__file__).resolve().parents[1]


def identity_id(kind: str, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://documind.example/{kind}/{name}")


def corpus_document_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://documint.local/demo-corpus/{key}")


def demo_manifest() -> Manifest:
    return Manifest.model_validate_json((ROOT / "demo_corpus/manifest.json").read_text("utf-8"))


def seed_corpus(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    manifest: Manifest,
    files: Path = ROOT / "demo_corpus/files",
) -> dict[str, UUID]:
    if settings.environment == "production":
        raise ValueError("demo corpus is forbidden in production")
    # Validate every file before any import; document contents are data, never instructions.
    uploads = {}
    for item in manifest.documents:
        if Path(item.file).name != item.file:
            raise ValueError("invalid corpus filename")
        upload = validate_upload(item.file, (files / item.file).read_bytes(), settings)
        if upload.sha256 != item.sha256 or len(upload.content) != item.size_bytes:
            raise ValueError("corpus integrity check failed")
        uploads[item.id] = upload
    if len(uploads) != len(manifest.documents):
        raise ValueError("duplicate corpus identifier")
    seed_identities(db, settings, demo_personas())
    admin = db.get(User, identity_id("personas", "admin"))
    if admin is None or admin.status != "ACTIVE":
        raise ValueError("demo administrator unavailable")
    service = DocumentService(db, load_actor(db, admin), storage, settings.processing_pipeline_key)
    result = {}
    for item in manifest.documents:
        key = corpus_document_id(item.id)
        owner, department = (
            identity_id("personas", item.owner),
            identity_id("departments", item.department),
        )
        expected_grants = {
            (identity_id("personas", person), None, "READ") for person in item.read_users
        } | {(None, role, "READ") for role in item.read_roles}
        document = db.get(Document, key)
        if document is None:
            document = Document(
                id=key,
                owner_id=owner,
                department_id=department,
                title=item.title,
                visibility=item.visibility,
            )
            db.add(document)
            db.flush()
            db.add_all(
                DocumentGrant(
                    document_id=key,
                    user_id=user,
                    role_name=role,
                    permission=permission,
                    granted_by=admin.id,
                )
                for user, role, permission in expected_grants
            )
        else:
            actual_grants = set(
                db.execute(
                    select(
                        DocumentGrant.user_id, DocumentGrant.role_name, DocumentGrant.permission
                    ).where(DocumentGrant.document_id == key)
                ).tuples()
            )
            if (
                document.owner_id != owner
                or document.department_id != department
                or document.title != item.title
                or document.visibility != item.visibility
                or document.archived
                or actual_grants != expected_grants
            ):
                raise ValueError("demo document changed; resolve fixture conflict explicitly")
        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == key, DocumentVersion.version_number == item.version
            )
        )
        if version is None:
            _, version = service.store_original(document, uploads[item.id], item.version)
        else:
            if (
                version.sha256 != item.sha256
                or version.size_bytes != item.size_bytes
                or version.filename != item.file
            ):
                raise ValueError("demo version conflicts with the checked corpus")
            if version.status in {"UPLOADING", "UPLOAD_FAILED"}:
                storage.put(version.object_key, uploads[item.id].content, version.media_type)
                version.status, version.error_code = "UPLOADED", None
            content = storage.get(version.object_key)
            if (
                hashlib.sha256(content).hexdigest() != item.sha256
                or len(content) != item.size_bytes
            ):
                raise ValueError("stored demo original failed integrity check")
            ensure_job(db, version.id, settings.processing_pipeline_key)
            db.commit()
        result[item.id] = version.id
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True)
    parser.add_argument(
        "--process", action="store_true", help="run the configured embedding provider"
    )
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            versions = seed_corpus(db, S3Storage(settings), settings, demo_manifest())
            print(f"PASS: {len(versions)} checked synthetic originals imported/reused")
            if args.process:
                for key, version_id in versions.items():
                    job = ensure_job(db, version_id, settings.processing_pipeline_key)
                    db.commit()
                    state = process_job(db, job.id, settings=settings)
                    print(f"{key}: {state}; provider={settings.embedding_provider}")
                    if state != "SUCCEEDED":
                        raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
