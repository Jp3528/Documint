"""Verify corpus permissions with real persisted identities; no retrieval quality claim."""

from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy.orm import Session, sessionmaker

from evals.schema import GoldenDataset, Manifest, reference_can_read
from packages.config import Settings
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.identity.policies import DocumentScope, RoleName, can_read_document
from scripts.seed_demo import demo_personas, seed_identities

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.infrastructure


def fixture_id(kind: str, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://documind.example/{kind}/{name}")


def test_database_actors_match_corpus_and_golden_access_contract(
    isolated_db: sessionmaker[Session],
) -> None:
    people = demo_personas()
    manifest = Manifest.model_validate_json((ROOT / "demo_corpus/manifest.json").read_text("utf-8"))
    golden = GoldenDataset.model_validate_json((ROOT / "evals/golden.json").read_text("utf-8"))
    scopes = {
        doc.id: DocumentScope(
            fixture_id("personas", doc.owner),
            fixture_id("departments", doc.department) if doc.department else None,
            doc.visibility,
            frozenset(fixture_id("personas", name) for name in doc.read_users),
            frozenset(RoleName(role) for role in doc.read_roles),
        )
        for doc in manifest.documents
    }
    with isolated_db() as db:
        assert seed_identities(db, Settings(environment="test"), people) == 10
        actors = {}
        for person in people.personas:
            user = db.get(User, fixture_id("personas", person.id))
            assert user is not None
            actor = actors[person.id] = load_actor(db, user)
            for doc in manifest.documents:
                expected = reference_can_read(person, doc)
                assert can_read_document(actor, scopes[doc.id]) == expected, (
                    person.id,
                    doc.id,
                )
        for case in golden.cases:
            actor = actors[case.persona]
            assert all(can_read_document(actor, scopes[key]) for key in case.expected_sources)
            assert all(not can_read_document(actor, scopes[key]) for key in case.forbidden_sources)
