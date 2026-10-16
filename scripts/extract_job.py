"""Run only extraction for an explicit job. Full indexing is connected in session 3C."""

import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.parsers.service import ExtractionService
from packages.storage import S3Storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            state = ExtractionService(db, S3Storage(settings), settings).run_stage(args.job_id)
            print(f"Extraction stage: {state}")
            if state == "FAILED":
                raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
