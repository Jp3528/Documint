"""Run one stored job through the complete pipeline using the configured provider."""

import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.processing.service import process_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            state = process_job(db, args.job_id, settings=settings)
            print(f"Pipeline: {state}; configured provider: {settings.embedding_provider}")
            if state not in {"SUCCEEDED", "RUNNING"}:
                raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
