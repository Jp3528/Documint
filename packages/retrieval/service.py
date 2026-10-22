"""Authorization precedes ranking/limits; vector distance sees only compatible profiles."""

import math

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CTE

from packages.documents.access import document_access
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.identity.policies import Actor
from packages.indexing.chunking import EmbeddingProfile
from packages.indexing.models import ChunkEmbedding, IndexChunk, IndexRevision
from packages.providers.contracts import EmbeddingProvider
from packages.providers.validation import embedding_profile, validate_batch

from .contracts import Candidate, RetrievalResult, SearchRequest


class RetrievalService:
    def __init__(self, db: Session, actor: Actor) -> None:
        self.db, self.actor = db, actor

    def _scope(self, request: SearchRequest, profile: EmbeddingProfile | None = None) -> CTE:
        query = (
            select(
                IndexChunk.id.label("chunk_id"),
                IndexChunk.index_revision_id,
                IndexRevision.version_id,
                Document.id.label("document_id"),
                Document.title,
                DocumentVersion.filename,
                IndexChunk.text,
                IndexChunk.sha256,
                IndexChunk.spans,
                IndexChunk.search_vector,
                ChunkEmbedding.embedding,
            )
            .join(IndexRevision, IndexRevision.id == IndexChunk.index_revision_id)
            .join(DocumentVersion, DocumentVersion.id == IndexRevision.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == IndexChunk.id)
            .where(
                document_access(self.actor),
                Document.archived.is_(False),
                Document.active_index_revision_id == IndexRevision.id,
                IndexRevision.status == "READY",
                DocumentVersion.status == "READY",
            )
        )
        if request.department_id:
            query = query.where(Document.department_id == request.department_id)
        if request.document_id:
            query = query.where(Document.id == request.document_id)
        if request.file_type:
            query = query.where(DocumentVersion.filename.endswith("." + request.file_type))
        if profile:
            query = query.where(
                IndexRevision.embedding_profile == profile.model_dump(),
                ChunkEmbedding.dimensions == profile.dimensions,
            )
        # Materialization also fences dimension-sensitive functions from incompatible vectors.
        return query.cte("authorized_chunks").prefix_with("MATERIALIZED")

    def _candidates(self, query: Select[tuple[object, ...]]) -> tuple[Candidate, ...]:
        result = []
        for rank, row in enumerate(self.db.execute(query).mappings(), 1):
            values = {
                key: row[key]
                for key in (
                    "chunk_id",
                    "document_id",
                    "version_id",
                    "index_revision_id",
                    "title",
                    "filename",
                    "text",
                    "sha256",
                    "spans",
                    "score",
                )
            }
            if math.isfinite(float(values["score"])):
                result.append(Candidate.model_validate(values | {"rank": rank}))
        return tuple(result)

    def lexical(self, request: SearchRequest) -> RetrievalResult:
        scope = self._scope(request)
        terms = func.websearch_to_tsquery("spanish", request.query)
        score = func.ts_rank_cd(scope.c.search_vector, terms, 32).label("score")
        query = (
            select(scope, score)
            .where(scope.c.search_vector.bool_op("@@")(terms))
            .order_by(score.desc(), scope.c.chunk_id)
            .limit(request.limit)
        )
        return RetrievalResult(
            method="lexical",
            strategy_version="spanish-fts-v1",
            embedding_mode=None,
            candidates=self._candidates(query),
        )

    def vector(self, request: SearchRequest, provider: EmbeddingProvider) -> RetrievalResult:
        scope = self._scope(request, embedding_profile(provider.model))
        empty = RetrievalResult(
            method="vector",
            strategy_version="cosine-exact-v1",
            embedding_mode=provider.model.mode,
            candidates=(),
        )
        if not self.db.scalar(select(scope.c.chunk_id).limit(1)):
            return empty
        self.db.commit()  # No locks during provider calls. The retrieval query rechecks SQL ACL.
        batch = provider.embed([request.query])
        validate_batch(batch, provider.model, 1)
        user = self.db.scalar(
            select(User).where(User.id == self.actor.id).execution_options(populate_existing=True)
        )
        if user is None:
            return empty.model_copy(update={"usage": batch.usage})
        self.actor = load_actor(self.db, user)
        scope = self._scope(request, embedding_profile(provider.model))
        distance = scope.c.embedding.cosine_distance(list(batch.vectors[0]))
        score = (1 - distance).label("score")
        query = select(scope, score).order_by(distance, scope.c.chunk_id).limit(request.limit)
        return empty.model_copy(
            update={"candidates": self._candidates(query), "usage": batch.usage}
        )
