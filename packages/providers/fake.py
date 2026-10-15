"""Offline deterministic test doubles; these do not measure semantic quality."""

import hashlib
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

from .contracts import Claim, EmbeddingBatch, LLMRequest, LLMResult, ModelInfo, Usage

INSUFFICIENT_EVIDENCE = "No encuentro evidencia suficiente para responder esta pregunta."
FAKE_USAGE = Usage(observed_cost_usd=Decimal("0"))


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int = 16) -> None:
        if not 1 <= dimensions <= 4096:
            raise ValueError("dimensions must be between 1 and 4096")
        self._model = ModelInfo("fake-sha256", "1", "FAKE", dimensions)
        self.dimensions = dimensions

    @property
    def model(self) -> ModelInfo:
        return self._model

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors: list[tuple[float, ...]] = []
        for value in texts:
            raw = b"".join(
                hashlib.sha256(value.encode("utf-8") + index.to_bytes(4, "big")).digest()
                for index in range((self.dimensions + 31) // 32)
            )[: self.dimensions]
            numbers = [(number - 127.5) / 127.5 for number in raw]
            norm = math.sqrt(sum(number * number for number in numbers))
            vectors.append(tuple(number / norm for number in numbers))
        return EmbeddingBatch(tuple(vectors), self.model, FAKE_USAGE)


class FakeLLMProvider:
    """Scripted by exact question. Unknown questions or missing sources always abstain.

    Supplied claims may deliberately be false for adversarial tests. This fake is not a
    support checker and the returned source labels are not validated persisted citations.
    """

    def __init__(self, answers: Mapping[str, tuple[Claim, ...]] | None = None) -> None:
        self._answers = dict(answers or {})

    @property
    def model(self) -> ModelInfo:
        return ModelInfo("fake-scripted", "1", "FAKE")

    def generate(self, request: LLMRequest) -> LLMResult:
        claims = self._answers.get(request.question, ())
        available = {source.source_id for source in request.evidence}
        if not claims or any(
            not claim.source_ids or not set(claim.source_ids).issubset(available)
            for claim in claims
        ):
            return LLMResult(INSUFFICIENT_EVIDENCE, (), self.model, FAKE_USAGE)
        return LLMResult(" ".join(claim.text for claim in claims), claims, self.model, FAKE_USAGE)
