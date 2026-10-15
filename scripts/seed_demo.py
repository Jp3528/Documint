"""Explicitly provision synthetic demo identities. Never run in production."""

import argparse
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from evals.schema import Personas
from packages.config import Settings, get_settings
from packages.database import make_engine
from packages.identity.models import User
from packages.identity.security import hash_password

# Public demo credential, documented in README. This is deliberately not a secret.
PUBLIC_DEMO_PASSWORD = "DocumindDemo2026!"


def demo_personas() -> Personas:
    path = Path(__file__).resolve().parents[1] / "evals/personas.json"
    return Personas.model_validate_json(path.read_text(encoding="utf-8"))


def seed_identities(db: Session, settings: Settings, people: Personas) -> int:
    if settings.environment == "production":
        raise ValueError("demo seeds are forbidden in production")
    created = 0
    for person in people.personas:
        expected_id = uuid5(NAMESPACE_URL, f"https://documind.example/personas/{person.id}")
        existing = db.scalar(select(User).where(User.email == person.email))
        if existing is not None:
            if existing.id != expected_id:
                raise ValueError("demo identity conflicts with an existing user")
            continue  # Do not reset existing credentials or statuses.
        db.add(
            User(
                id=expected_id,
                email=person.email,
                display_name=person.id.replace("_", " ").title(),
                password_hash=hash_password(PUBLIC_DEMO_PASSWORD),
                status="ACTIVE" if person.active else "INACTIVE",
            )
        )
        created += 1
    db.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True)
    parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        with Session(engine) as db:
            count = seed_identities(db, settings, demo_personas())
        print(f"PASS: {count} synthetic identities created; existing credentials preserved")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
