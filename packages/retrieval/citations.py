"""Citations are reconstructed from published immutable rows, never from client/LLM text."""

import hashlib
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.documents.access import document_access
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import NotFoundError, load_actor
from packages.identity.policies import Actor
from packages.indexing.chunking import ChunkSpan
from packages.indexing.models import IndexChunk, IndexRevision
from packages.parsers.contracts import Locator
from packages.providers.contracts import Usage

from .contracts import RetrievalResult


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    index_revision_id: UUID
    version_number: int
    title: str
    filename: str
    sha256: str
    snippet: str = Field(max_length=500)
    locators: tuple[Locator, ...]
    source_url: str
    original_url: str


class SourceView(Citation):
    text: str
    spans: tuple[ChunkSpan, ...]


class SearchHit(Citation):
    score: float
    rank: int


class SearchView(BaseModel):
    method: str
    strategy_version: str
    embedding_mode: str | None
    configuration: dict[str, str | int | float] | None
    usage: Usage
    candidates: tuple[SearchHit, ...]


class CitationService:
    def __init__(self, db: Session, actor: Actor) -> None:
        self.db, self.actor = db, actor

    def sources(
        self,
        chunk_ids: Sequence[UUID],
        *,
        active_only: bool = False,
    ) -> dict[UUID, SourceView]:
        if not chunk_ids:
            return {}
        user = self.db.scalar(
            select(User).where(User.id == self.actor.id).execution_options(populate_existing=True)
        )
        if user is None:
            return {}
        actor = load_actor(self.db, user)
        query = (
            select(IndexChunk, IndexRevision, DocumentVersion, Document)
            .join(IndexRevision, IndexRevision.id == IndexChunk.index_revision_id)
            .join(DocumentVersion, DocumentVersion.id == IndexRevision.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                IndexChunk.id.in_(chunk_ids),
                document_access(actor),
                IndexRevision.status == "READY",
                DocumentVersion.status == "READY",
            )
            .execution_options(populate_existing=True)
        )
        if active_only:
            query = query.where(
                Document.archived.is_(False), Document.active_index_revision_id == IndexRevision.id
            )
        rows = self.db.execute(query)
        result = {}
        for chunk, revision, version, document in rows:
            if hashlib.sha256(chunk.text.encode()).hexdigest() != chunk.sha256:
                continue  # Corrupted evidence is never cited, even if metadata looks valid.
            spans = tuple(ChunkSpan.model_validate(value) for value in chunk.spans)
            locators = []
            for span in spans:
                if span.locator not in locators:
                    locators.append(span.locator)
            snippet = chunk.text if len(chunk.text) <= 500 else chunk.text[:499] + "…"
            result[chunk.id] = SourceView(
                chunk_id=chunk.id,
                document_id=document.id,
                version_id=version.id,
                index_revision_id=revision.id,
                version_number=version.version_number,
                title=document.title,
                filename=version.filename,
                sha256=chunk.sha256,
                snippet=snippet,
                locators=tuple(locators),
                text=chunk.text,
                spans=spans,
                source_url=f"/sources/{chunk.id}",
                original_url=f"/documents/{document.id}/versions/{version.id}/original",
            )
        return result

    def source(self, chunk_id: UUID) -> SourceView:
        value = self.sources([chunk_id]).get(chunk_id)
        if value is None:
            raise NotFoundError
        return value

    def search_view(self, result: RetrievalResult) -> SearchView:
        sources = self.sources([candidate.chunk_id for candidate in result.candidates])
        hits: list[SearchHit] = []
        for candidate in result.candidates:
            if candidate.chunk_id in sources:
                data = sources[candidate.chunk_id].model_dump(exclude={"text", "spans"})
                hits.append(
                    SearchHit.model_validate(
                        data | {"rank": len(hits) + 1, "score": candidate.score}
                    )
                )
        return SearchView(
            method=result.method,
            strategy_version=result.strategy_version,
            embedding_mode=result.embedding_mode,
            configuration=result.configuration,
            usage=result.usage,
            candidates=tuple(hits),
        )
