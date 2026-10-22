"""Authorization precedes ranking/limits; vector distance sees only compatible profiles."""

import math
import re
from uuid import UUID

from sqlalchemy import Select, String, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from packages.documents.access import document_access
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.identity.policies import Actor
from packages.indexing.chunking import EmbeddingProfile
from packages.indexing.models import ChunkEmbedding, IndexChunk, IndexRevision
from packages.providers.contracts import EmbeddingProvider, Usage
from packages.providers.validation import embedding_profile, validate_batch

from .contracts import Candidate, RetrievalResult, SearchRequest
from .fusion import DEFAULT_FUSION, FusionConfig, fuse


class RetrievalService:
    def __init__(
        self,
        db: Session,
        actor: Actor,
        *,
        document_ids: frozenset[UUID] | None = None,
    ) -> None:
        self.db, self.actor = db, actor
        self.document_ids = document_ids

    def _refresh_actor(self) -> bool:
        user = self.db.scalar(
            select(User).where(User.id == self.actor.id).execution_options(populate_existing=True)
        )
        if user is None:
            return False
        self.actor = load_actor(self.db, user)
        return self.actor.active

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
        if self.document_ids is not None:
            query = query.where(Document.id.in_(self.document_ids))
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
        terms: ColumnElement[str]
        if re.search(r'"|(?<!\S)-\S|\bOR\b', request.query, flags=re.IGNORECASE):
            terms = func.websearch_to_tsquery("spanish", request.query)
        else:
            # Turn PostgreSQL's safely quoted lexemes into an ANY-word query. Natural
            # questions contain terms that need not all occur in the same source chunk.
            plain = cast(func.plainto_tsquery("spanish", request.query), String)
            terms = cast(func.replace(plain, " & ", " | "), TSQUERY)
        score = func.ts_rank_cd(scope.c.search_vector, terms, 32).label("score")
        query = (
            select(scope, score)
            .where(scope.c.search_vector.bool_op("@@")(terms))
            .order_by(score.desc(), scope.c.chunk_id)
            .limit(request.limit)
        )
        return RetrievalResult(
            method="lexical",
            strategy_version="spanish-fts-v2",
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
        if not self._refresh_actor():
            return empty.model_copy(update={"usage": batch.usage})
        scope = self._scope(request, embedding_profile(provider.model))
        distance = scope.c.embedding.cosine_distance(list(batch.vectors[0]))
        score = (1 - distance).label("score")
        query = select(scope, score).order_by(distance, scope.c.chunk_id).limit(request.limit)
        return empty.model_copy(
            update={"candidates": self._candidates(query), "usage": batch.usage}
        )

    def hybrid(
        self,
        request: SearchRequest,
        provider: EmbeddingProvider,
        config: FusionConfig = DEFAULT_FUSION,
    ) -> RetrievalResult:
        pool = request.model_copy(update={"limit": config.candidate_pool})
        vector = self.vector(pool, provider) if config.vector_weight else None
        lexical = self.lexical(pool) if config.lexical_weight else None
        result = RetrievalResult(
            method="hybrid",
            strategy_version=config.version,
            configuration=config.model_dump(),
            embedding_mode=vector.embedding_mode if vector else None,
            candidates=(),
            usage=vector.usage if vector else Usage(),
        )
        if not self._refresh_actor():
            return result
        lexical_rows = lexical.candidates if lexical else ()
        vector_rows = vector.candidates if vector else ()
        ids = {row.chunk_id for row in (*lexical_rows, *vector_rows)}
        if not ids:
            return result
        scope = self._scope(request)
        allowed = set(self.db.scalars(select(scope.c.chunk_id).where(scope.c.chunk_id.in_(ids))))
        ranked = fuse(
            [row for row in lexical_rows if row.chunk_id in allowed],
            [row for row in vector_rows if row.chunk_id in allowed],
            request.limit,
            config,
        )
        return result.model_copy(update={"candidates": ranked})
