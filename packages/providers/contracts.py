"""Provider boundary. Source labels are proposals; services must validate real citations."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(frozen=True)
class ModelInfo:
    name: str
    revision: str
    mode: Literal["FAKE", "REAL"]
    dimensions: int | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    observed_cost_usd: Decimal | None = None


@dataclass(frozen=True)
class Evidence:
    source_id: str
    text: str


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    question: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Claim:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class LLMResult:
    text: str
    claims: tuple[Claim, ...]
    model: ModelInfo
    usage: Usage


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    model: ModelInfo
    usage: Usage


class LLMProvider(Protocol):
    @property
    def model(self) -> ModelInfo: ...

    def generate(self, request: LLMRequest) -> LLMResult: ...


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> ModelInfo: ...

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...
