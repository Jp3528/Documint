from collections import Counter
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.identity.policies import Actor
from packages.indexing.models import IndexChunk
from packages.providers.contracts import Evidence, LLMRequest
from packages.retrieval.citations import CitationService, SourceView
from packages.retrieval.contracts import Candidate

from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, token_upper_bound


class ContextBudgetError(Exception):
    pass


class ContextConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    token_budget: int = Field(default=6000, ge=1024, le=32000)
    max_chunks: int = Field(default=8, ge=1, le=20)
    max_per_document: int = Field(default=3, ge=1, le=10)
    neighbor_radius: int = Field(default=0, ge=0, le=1)


DEFAULT_CONTEXT = ContextConfig()


class ContextPackage(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: LLMRequest
    prompt_version: str = PROMPT_VERSION
    counter_version: str = "utf8-byte-upper-bound-v1"
    token_upper_bound: int
    token_budget: int
    source_ids: tuple[UUID, ...]


class ContextBuilder:
    def __init__(self, db: Session, actor: Actor, config: ContextConfig = DEFAULT_CONTEXT) -> None:
        self.db, self.actor, self.config = db, actor, config

    def build(self, question: str, candidates: tuple[Candidate, ...]) -> ContextPackage:
        citations = CitationService(self.db, self.actor)
        sources = citations.sources(
            [candidate.chunk_id for candidate in candidates], active_only=True
        )
        ordered = list(
            dict.fromkeys(
                candidate.chunk_id for candidate in candidates if candidate.chunk_id in sources
            )
        )
        if self.config.neighbor_radius:
            neighbors: list[UUID] = []
            primary = {
                row.id: row
                for row in self.db.scalars(select(IndexChunk).where(IndexChunk.id.in_(ordered)))
            }
            for key in ordered:
                row = primary[key]
                neighbors.extend(
                    self.db.scalars(
                        select(IndexChunk.id)
                        .where(
                            IndexChunk.index_revision_id == row.index_revision_id,
                            IndexChunk.position.in_([row.position - 1, row.position + 1]),
                        )
                        .order_by(IndexChunk.position)
                    )
                )
            ordered = list(dict.fromkeys([*ordered, *neighbors]))
        sources = citations.sources(ordered, active_only=True)
        ordered = [key for key in ordered if key in sources]
        chosen: list[SourceView] = []
        hashes: set[str] = set()
        per_document: Counter[UUID] = Counter()

        def request() -> LLMRequest:
            return LLMRequest(
                SYSTEM_PROMPT,
                question,
                tuple(Evidence(str(source.chunk_id), source.text) for source in chosen),
            )

        if token_upper_bound(request()) > self.config.token_budget:
            raise ContextBudgetError("La pregunta y el contrato superan el presupuesto de contexto")
        for key in ordered:
            source = sources[key]
            if (
                source.sha256 in hashes
                or len(chosen) >= self.config.max_chunks
                or per_document[source.document_id] >= self.config.max_per_document
            ):
                continue
            chosen.append(source)
            if token_upper_bound(request()) > self.config.token_budget:
                chosen.pop()
                continue
            hashes.add(source.sha256)
            per_document[source.document_id] += 1
        value = request()
        return ContextPackage(
            request=value,
            source_ids=tuple(source.chunk_id for source in chosen),
            token_upper_bound=token_upper_bound(value),
            token_budget=self.config.token_budget,
        )
