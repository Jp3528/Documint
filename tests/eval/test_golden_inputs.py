import hashlib
from collections import Counter
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from evals.schema import GoldenDataset, Manifest, Personas, reference_can_read

ROOT = Path(__file__).resolve().parents[2]


def extract_fixture(path: Path) -> str:
    """Small independent check of authored files, not the production parser registry."""
    if path.suffix == ".pdf":
        return " ".join(page.extract_text() for page in PdfReader(path).pages)
    if path.suffix == ".docx":
        return " ".join(p.text for p in Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8")


def test_corpus_hashes_formats_and_reference_quotes_are_real() -> None:
    manifest = Manifest.model_validate_json((ROOT / "demo_corpus/manifest.json").read_text("utf-8"))
    dataset = GoldenDataset.model_validate_json((ROOT / "evals/golden.json").read_text("utf-8"))
    assert manifest.version == dataset.corpus_version
    assert len(manifest.documents) == len({doc.id for doc in manifest.documents}) == 8
    assert Counter(Path(doc.file).suffix for doc in manifest.documents) == {
        ".pdf": 2,
        ".docx": 2,
        ".txt": 2,
        ".md": 2,
    }
    extracted = {}
    files_dir = ROOT / "demo_corpus/files"
    assert {p.name for p in files_dir.iterdir()} == {doc.file for doc in manifest.documents}
    for doc in manifest.documents:
        path = (files_dir / doc.file).resolve()
        assert path.is_relative_to(files_dir.resolve())
        raw = path.read_bytes()
        if path.suffix in {".md", ".txt"}:
            assert b"\r\n" not in raw, "published text hashes must survive Git LF normalization"
        assert len(raw) == doc.size_bytes
        assert hashlib.sha256(raw).hexdigest() == doc.sha256
        extracted[doc.id] = " ".join(extract_fixture(path).split())
        assert "ficticio" in extracted[doc.id]
    for case in dataset.cases:
        for item in case.evidence:
            assert item.quote in extracted[item.document_id], (case.id, item.document_id)


def test_dataset_categories_personas_and_access_expectations() -> None:
    manifest = Manifest.model_validate_json((ROOT / "demo_corpus/manifest.json").read_text("utf-8"))
    dataset = GoldenDataset.model_validate_json((ROOT / "evals/golden.json").read_text("utf-8"))
    people = Personas.model_validate_json((ROOT / "evals/personas.json").read_text("utf-8"))
    personas = {person.id: person for person in people.personas}
    docs = {doc.id: doc for doc in manifest.documents}
    assert len(personas) == len(people.personas)
    assert len(dataset.cases) == len({case.id for case in dataset.cases}) == 24
    assert Counter(case.category for case in dataset.cases) == {
        "answerable": 12,
        "no_evidence": 6,
        "restricted": 6,
    }
    assert sum(len(case.expected_sources) > 1 for case in dataset.cases) == 4
    for document in docs.values():
        assert document.owner in personas
        assert set(document.read_users).issubset(personas)
    for case in dataset.cases:
        persona = personas[case.persona]
        assert all(reference_can_read(persona, docs[key]) for key in case.expected_sources)
        assert all(not reference_can_read(persona, docs[key]) for key in case.forbidden_sources)
    assert reference_can_read(personas["auditor_granted"], docs["incident"])
    assert not reference_can_read(personas["auditor"], docs["incident"])
    assert not reference_can_read(personas["auditor"], docs["travel"])
