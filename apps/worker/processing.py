from uuid import UUID

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.processing.service import process_job


def process_document(job_id: str) -> dict[str, str]:
    try:
        parsed = UUID(job_id)
    except ValueError:
        return {"status": "INVALID_JOB"}
    engine = make_engine(get_settings())
    try:
        with Session(engine, expire_on_commit=False) as db:
            return {"status": process_job(db, parsed)}
    finally:
        engine.dispose()
