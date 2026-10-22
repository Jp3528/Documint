"""Explicit FAKE/REAL retrieval evaluation. Fake results never certify semantic quality."""

import hashlib
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session

from evals.schema import GoldenDataset, Manifest, Personas, reference_can_read
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.indexing.models import IndexRevision
from packages.parsers.models import Extraction
from packages.providers.contracts import (
    EmbeddingBatch,
    EmbeddingProvider,
    ModelInfo,
    ProviderError,
    Usage,
)
from packages.providers.validation import embedding_profile, validate_batch
from packages.retrieval.contracts import SearchRequest
from packages.retrieval.fusion import DEFAULT_FUSION
from packages.retrieval.service import RetrievalService
from scripts.seed_corpus import corpus_document_id, identity_id


class EvaluationError(Exception):
    pass


def relevance_metrics(expected: set[str], ranked: list[str]) -> tuple[float | None, float | None]:
    if not expected:
        return None, None
    recall = len(expected.intersection(ranked)) / len(expected)
    reciprocal = next(
        (1 / rank for rank, source in enumerate(ranked, 1) if source in expected), 0.0
    )
    return recall, reciprocal


class RecordingProvider:
    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider
        self.receipts: list[Usage] = []
        self.attempts = 0
        self.cache: dict[tuple[str, ...], EmbeddingBatch] = {}

    @property
    def model(self) -> ModelInfo:
        return self.provider.model

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        key = tuple(texts)
        if key not in self.cache:
            self.attempts += 1
            value = self.provider.embed(texts)
            validate_batch(value, self.model, len(texts))
            self.cache[key] = value
            self.receipts.append(value.usage)
        return self.cache[key]


class CaseResult(BaseModel):
    case_id: str
    persona: str
    category: str
    method: str
    retrieved_sources: list[str]
    chunk_ids: list[UUID]
    recall_at_k: float | None
    reciprocal_rank: float | None
    unauthorized_hits: int
    forbidden_hits: int
    elapsed_ms: float
    error_code: str | None = None


class IndexSnapshot(BaseModel):
    version_id: UUID
    parser_revision: str
    normalized_sha256: str
    chunk_config: dict[str, str | int]
    chunk_count: int


class EvaluationReport(BaseModel):
    run_id: UUID
    mode: Literal["FAKE", "REAL"]
    status: Literal["TECHNICAL_ONLY", "EVALUATED"]
    created_at: datetime
    git_commit: str
    git_dirty: bool
    implementation_sha256: str
    corpus_version: str
    dataset_version: str
    corpus_sha256: str
    dataset_sha256: str
    model: ModelInfo
    top_k: int
    fusion_configuration: dict[str, str | int | float]
    retrieval_versions: dict[str, str]
    active_revisions: dict[str, UUID]
    index_configuration: dict[str, IndexSnapshot]
    query_provider_calls: int
    query_successful_responses: int
    query_input_tokens: int | None
    query_observed_cost_usd: Decimal | None
    cost_scope: str
    summaries: dict[str, dict[str, float | int]]
    cases: list[CaseResult]


def evaluate_retrieval(
    db: Session,
    provider: EmbeddingProvider,
    mode: Literal["FAKE", "REAL"],
    manifest: Manifest,
    people: Personas,
    golden: GoldenDataset,
    top_k: int = 5,
) -> EvaluationReport:
    if provider.model.mode != mode:
        raise EvaluationError("evaluation mode must match the actual provider")
    if not 1 <= top_k <= 50 or golden.corpus_version != manifest.version:
        raise EvaluationError("incompatible dataset or top-k")
    document_keys = {item.id for item in manifest.documents}
    persona_keys = {person.id for person in people.personas}
    if (
        not any(case.category == "answerable" for case in golden.cases)
        or len(document_keys) != len(manifest.documents)
        or len(persona_keys) != len(people.personas)
        or any(
            case.persona not in persona_keys
            or not (set(case.expected_sources) | set(case.forbidden_sources)) <= document_keys
            for case in golden.cases
        )
    ):
        raise EvaluationError("invalid evaluation references")
    profile = embedding_profile(provider.model).model_dump()
    keys = {corpus_document_id(item.id): item.id for item in manifest.documents}
    active = {}
    snapshots = {}
    for item in manifest.documents:
        document = db.get(Document, corpus_document_id(item.id))
        if not document or not document.active_index_revision_id or document.archived:
            raise EvaluationError("all checked corpus documents need an active index")
        revision = db.get(IndexRevision, document.active_index_revision_id)
        if not revision or revision.status != "READY" or revision.embedding_profile != profile:
            raise EvaluationError("corpus active profile does not match the evaluation provider")
        version = db.get(DocumentVersion, revision.version_id)
        if (
            not version
            or version.status != "READY"
            or version.sha256 != item.sha256
            or version.size_bytes != item.size_bytes
            or version.version_number != item.version
        ):
            raise EvaluationError("corpus version does not match the checked manifest")
        active[item.id] = revision.id
        extraction = db.get(Extraction, revision.extraction_id)
        if extraction is None:
            raise EvaluationError("indexed extraction missing")
        snapshots[item.id] = IndexSnapshot(
            version_id=version.id,
            parser_revision=extraction.parser_revision,
            normalized_sha256=extraction.normalized_sha256,
            chunk_config=revision.chunk_config,
            chunk_count=revision.chunk_count,
        )
    personas = {person.id: person for person in people.personas}
    recorded = RecordingProvider(provider)
    rows: list[CaseResult] = []
    strategies: dict[str, str] = {}
    methods: tuple[Literal["lexical", "vector", "hybrid"], ...] = ("lexical", "vector", "hybrid")
    for case in golden.cases:
        person = personas[case.persona]
        user = db.get(User, identity_id("personas", person.id))
        if user is None:
            raise EvaluationError("evaluation persona missing")
        actor = load_actor(db, user)
        if actor.active != person.active or {role.value for role in actor.roles} != set(
            person.roles
        ):
            raise EvaluationError("persona status/roles differ from checked fixtures")
        retrieval = RetrievalService(db, actor, document_ids=frozenset(keys))
        allowed = {item.id for item in manifest.documents if reference_can_read(person, item)}
        for method in methods:
            started = perf_counter()
            request = SearchRequest(query=case.question, method=method, limit=top_k)
            try:
                result = (
                    retrieval.lexical(request)
                    if method == "lexical"
                    else retrieval.vector(request, recorded)
                    if method == "vector"
                    else retrieval.hybrid(request, recorded)
                )
            except ProviderError as exc:
                db.rollback()
                strategies.setdefault(method, "FAILED_BEFORE_RESULT")
                rows.append(
                    CaseResult(
                        case_id=case.id,
                        persona=case.persona,
                        category=case.category,
                        method=method,
                        retrieved_sources=[],
                        chunk_ids=[],
                        recall_at_k=None,
                        reciprocal_rank=None,
                        unauthorized_hits=0,
                        forbidden_hits=0,
                        error_code=exc.code,
                        elapsed_ms=round((perf_counter() - started) * 1000, 3),
                    )
                )
                continue
            ranked = [keys[candidate.document_id] for candidate in result.candidates]
            strategies[method] = result.strategy_version
            recall, reciprocal = relevance_metrics(set(case.expected_sources), ranked)
            rows.append(
                CaseResult(
                    case_id=case.id,
                    persona=case.persona,
                    category=case.category,
                    method=method,
                    retrieved_sources=ranked,
                    chunk_ids=[c.chunk_id for c in result.candidates],
                    recall_at_k=recall,
                    reciprocal_rank=reciprocal,
                    unauthorized_hits=sum(source not in allowed for source in ranked),
                    forbidden_hits=sum(source in case.forbidden_sources for source in ranked),
                    elapsed_ms=round((perf_counter() - started) * 1000, 3),
                )
            )
    summaries: dict[str, dict[str, float | int]] = {}
    for method in methods:
        selected = [row for row in rows if row.method == method]
        answerable = [row for row in selected if row.category == "answerable"]
        summaries[method] = {
            "answerable_cases": len(answerable),
            "mean_recall_at_k": sum(row.recall_at_k or 0 for row in answerable) / len(answerable),
            "mrr": sum(row.reciprocal_rank or 0 for row in answerable) / len(answerable),
            "unauthorized_hits": sum(row.unauthorized_hits for row in selected),
            "forbidden_hits": sum(row.forbidden_hits for row in selected),
            "failed_cases": sum(row.error_code is not None for row in selected),
        }
    costs = [usage.observed_cost_usd for usage in recorded.receipts]
    tokens = [usage.input_tokens for usage in recorded.receipts]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    from scripts.seed_corpus import ROOT

    implementation = hashlib.sha256()
    paths = sorted(
        [
            *ROOT.glob("packages/**/*.py"),
            *ROOT.glob("evals/*.py"),
            *ROOT.glob("scripts/*.py"),
            ROOT / "uv.lock",
            ROOT / "pyproject.toml",
        ]
    )
    for path in paths:
        implementation.update(path.relative_to(ROOT).as_posix().encode())
        implementation.update(path.read_bytes())
    return EvaluationReport(
        run_id=uuid4(),
        mode=mode,
        status="TECHNICAL_ONLY" if mode == "FAKE" else "EVALUATED",
        created_at=datetime.now(UTC),
        git_commit=commit,
        git_dirty=dirty,
        implementation_sha256=implementation.hexdigest(),
        corpus_version=manifest.version,
        dataset_version=golden.version,
        corpus_sha256=hashlib.sha256(manifest.model_dump_json().encode()).hexdigest(),
        dataset_sha256=hashlib.sha256(golden.model_dump_json().encode()).hexdigest(),
        model=provider.model,
        retrieval_versions=strategies,
        top_k=top_k,
        fusion_configuration=DEFAULT_FUSION.model_dump(),
        active_revisions=active,
        index_configuration=snapshots,
        query_provider_calls=recorded.attempts,
        query_successful_responses=len(recorded.receipts),
        query_input_tokens=sum(value for value in tokens if value is not None)
        if tokens and all(value is not None for value in tokens)
        else None,
        query_observed_cost_usd=sum((value for value in costs if value is not None), Decimal(0))
        if costs and all(value is not None for value in costs)
        else None,
        cost_scope=(
            "Only observed query requests in this run; excludes prior indexing and lost responses."
        ),
        summaries=summaries,
        cases=rows,
    )
