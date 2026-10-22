from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.indexing.chunking import ChunkSpan
from packages.providers.contracts import Usage


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1000)
    method: Literal["lexical", "vector"] = "lexical"
    limit: int = Field(default=10, ge=1, le=50)
    department_id: UUID | None = None
    document_id: UUID | None = None
    file_type: Literal["pdf", "docx", "txt", "md"] | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    index_revision_id: UUID
    title: str
    filename: str
    text: str
    sha256: str
    spans: tuple[ChunkSpan, ...]
    score: float
    rank: int


class RetrievalResult(BaseModel):
    method: Literal["lexical", "vector"]
    strategy_version: str
    embedding_mode: Literal["FAKE", "REAL"] | None
    candidates: tuple[Candidate, ...]
    usage: Usage = Usage()
