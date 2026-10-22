import math
from dataclasses import asdict

from packages.indexing.chunking import EmbeddingProfile

from .contracts import EmbeddingBatch, ModelInfo, ProviderError


def embedding_profile(model: ModelInfo) -> EmbeddingProfile:
    return EmbeddingProfile.model_validate(asdict(model))


def validate_batch(batch: EmbeddingBatch, expected: ModelInfo, count: int) -> None:
    if batch.model != expected:
        raise ProviderError("EMBEDDING_MODEL_MISMATCH")
    if len(batch.vectors) != count:
        raise ProviderError("EMBEDDING_COUNT_MISMATCH")
    for vector in batch.vectors:
        if len(vector) != expected.dimensions:
            raise ProviderError("EMBEDDING_DIMENSION_MISMATCH")
        if any(not math.isfinite(value) or abs(value) > 3.4028234e38 for value in vector):
            raise ProviderError("EMBEDDING_INVALID_VECTOR")
        if not any(abs(value) >= 1.17549435e-38 for value in vector):
            raise ProviderError("EMBEDDING_INVALID_VECTOR")
    usage = batch.usage
    if (usage.input_tokens is not None and usage.input_tokens < 0) or (
        usage.observed_cost_usd is not None
        and (not usage.observed_cost_usd.is_finite() or usage.observed_cost_usd < 0)
    ):
        raise ProviderError("EMBEDDING_INVALID_USAGE")
