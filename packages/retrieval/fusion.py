"""Weighted reciprocal rank fusion; raw FTS and cosine scores are never added."""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Candidate


class FusionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    version: str = "weighted-rrf-v1"
    rank_constant: int = Field(default=60, ge=1, le=1000)
    lexical_weight: float = Field(default=1, ge=0, le=10)
    vector_weight: float = Field(default=1, ge=0, le=10)
    candidate_pool: int = Field(default=50, ge=1, le=100)
    max_per_document: int = Field(default=3, ge=1, le=50)

    @model_validator(mode="after")
    def nonzero_weight(self) -> "FusionConfig":
        if self.lexical_weight + self.vector_weight <= 0:
            raise ValueError("at least one retriever must be enabled")
        return self


DEFAULT_FUSION = FusionConfig()


def fuse(
    lexical: Sequence[Candidate],
    vector: Sequence[Candidate],
    limit: int,
    config: FusionConfig = DEFAULT_FUSION,
) -> tuple[Candidate, ...]:
    scores: dict[UUID, float] = defaultdict(float)
    candidates = {}
    for rows, weight in [(lexical, config.lexical_weight), (vector, config.vector_weight)]:
        if weight == 0:
            continue
        seen: set[UUID] = set()
        for row in rows:
            if row.chunk_id in seen:
                continue
            seen.add(row.chunk_id)
            scores[row.chunk_id] += weight / (config.rank_constant + len(seen))
            candidates[row.chunk_id] = row
    chosen: list[Candidate] = []
    documents = defaultdict[UUID, int](int)
    for chunk_id in sorted(scores, key=lambda key: (-scores[key], key)):
        row = candidates[chunk_id]
        if documents[row.document_id] >= config.max_per_document:
            continue
        documents[row.document_id] += 1
        chosen.append(row.model_copy(update={"score": scores[chunk_id], "rank": len(chosen) + 1}))
        if len(chosen) == limit:
            break
    return tuple(chosen)
