"""Publish durable pending jobs once or as a local dispatch service."""

import argparse
import time
from uuid import UUID

from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.config import get_settings
from packages.database import make_engine
from packages.processing.service import dispatch_pending


def publish(job_id: UUID) -> None:
    celery_app.send_task("documind.process_document", args=[str(job_id)], retry=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    engine = make_engine(get_settings())
    try:
        while True:
            with Session(engine, expire_on_commit=False) as db:
                counts = dispatch_pending(db, publish)
            if any(counts.values()) or not args.watch:
                print(counts, flush=True)
            if not args.watch:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
